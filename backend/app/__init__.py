import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from flask import Flask, g, send_from_directory, jsonify, request
from flask_wtf.csrf import CSRFError
from sqlalchemy import event, text
from werkzeug.exceptions import HTTPException
from .extensions import db, csrf
from . import config as cfg

FRONTEND_DIST = cfg.REPO_ROOT / 'frontend' / 'dist'

# Ordered, versioned migrations. Each migration is additive and idempotently
# inspects the historical schema because older releases altered columns without
# recording a version. Future changes append a new version; they never rewrite a
# migration that may already have run on a user's private database.
_MIGRATIONS = (
    (1, 'record historical additive columns', (
        ('face_dataset', 'kind', 'VARCHAR(16)'),
        ('face_dataset', 'concept_desc', 'TEXT'),
        ('face_dataset', 'concept_terms', 'TEXT'),
        ('face_dataset', 'ref_original_filename', 'VARCHAR(255)'),
        ('face_dataset', 'fidelity', 'VARCHAR(8)'),
        ('face_dataset', 'train_settings', 'TEXT'),
        ('face_dataset', 'train_vae_path', 'TEXT'),
        ('face_dataset', 'train_te_path', 'TEXT'),
        ('face_dataset_image', 'fail_reason', 'TEXT'),
        ('face_dataset_image', 'parent_image_id', 'INTEGER'),
        ('face_dataset_image', 'derivation_kind', 'VARCHAR(32)'),
        ('face_dataset_image', 'upscale_ratio', 'REAL'),
        ('face_dataset_image', 'watermark_state', 'VARCHAR(16)'),
        ('face_dataset_image', 'watermark_bbox', 'TEXT'),
        ('face_dataset_image', 'watermark_regions', 'TEXT'),
        ('face_dataset_image', 'source_name', 'VARCHAR(255)'),
        ('face_dataset_image', 'original_filename', 'VARCHAR(255)'),
        ('face_dataset_image', 'source_sha256', 'VARCHAR(64)'),
        ('face_dataset_image', 'analysis_json', 'TEXT'),
        ('face_dataset_image', 'training_usefulness', 'VARCHAR(8)'),
        ('face_dataset_image', 'coverage_value', 'VARCHAR(8)'),
        ('face_dataset_image', 'perceptual_hash', 'VARCHAR(16)'),
        ('face_dataset_image', 'duplicate_of_id', 'INTEGER'),
        ('face_dataset_image', 'anchor_decision', 'VARCHAR(12)'),
        ('face_dataset_image', 'coverage_json', 'TEXT'),
        ('face_dataset_image', 'generation_anchor_ids', 'TEXT'),
        ('face_dataset_image', 'generation_anchor_metadata', 'TEXT'),
        ('face_dataset_image', 'generation_engine', 'VARCHAR(24)'),
        ('face_dataset_image', 'generation_gap_ids', 'TEXT'),
        ('training_run_record', 'settings', 'TEXT'),
        ('lora_test_image', 'error', 'TEXT'),
    )),
    (2, 'recoverable dataset deletion', (
        ('face_dataset', 'trashed_at', 'DATETIME'),
        ('face_dataset', 'trash_entry_id', 'VARCHAR(160)'),
    )),
    (3, 'durable background job ledger', ()),
    (4, 'remote generation provenance', (
        ('face_dataset_image', 'generation_provenance', 'TEXT'),
    )),
    (5, 'training admission provenance', (
        ('training_run_record', 'preflight', 'TEXT'),
        ('training_run_record', 'overrides', 'TEXT'),
    )),
    (6, 'enforce relational and enum integrity', ()),
    (7, 'curation history and undo', ()),
    (8, 'dataset image revision tracking', (
        ('face_dataset', 'revision', 'INTEGER NOT NULL DEFAULT 0'),
    )),
    (9, 'coverage evidence rights and policy', (
        ('face_dataset', 'coverage_profile', 'VARCHAR(16)'),
        ('face_dataset', 'coverage_targets', 'TEXT'),
        ('face_dataset_image', 'coverage_provenance', 'TEXT'),
        ('face_dataset_image', 'source_rights', 'TEXT'),
    )),
    (10, 'cloud billing and timing evidence', (
        ('cloud_training_run', 'billing_started_at', 'DATETIME'),
        ('cloud_training_run', 'billing_ended_at', 'DATETIME'),
        ('cloud_training_run', 'training_started_at', 'DATETIME'),
        ('cloud_training_run', 'estimated_minutes', 'REAL'),
        ('cloud_training_run', 'estimated_cost_usd', 'REAL'),
    )),
    (11, 'link studio evidence to training launches', (
        ('lora_test_image', 'training_run_record_id', 'INTEGER'),
    )),
    (12, 'enforce dataset coverage policy integrity', ()),
)


def _guard_triggers(table, valid_expression):
    """SQLite cannot add CHECK/FK constraints with ALTER TABLE. Existing
    installations therefore receive equivalent insert/update guards while new
    databases get native constraints from models.py. Keeping both paths makes
    an upgraded database just as strict as a fresh one without rebuilding large
    image/job tables in place."""
    statements = []
    for operation in ('INSERT', 'UPDATE'):
        name = f'trg_{table}_integrity_{operation.lower()}'
        statements.append(
            f'CREATE TRIGGER IF NOT EXISTS {name} BEFORE {operation} ON {table} '
            f'WHEN NOT ({valid_expression}) BEGIN '
            f"SELECT RAISE(ABORT, 'integrity constraint failed: {table}'); END")
    return statements


_MIGRATION_SQL = {
    6: tuple(
        _guard_triggers(
            'face_dataset',
            "(NEW.kind IS NULL OR NEW.kind IN ('', 'character', 'concept', 'style')) "
            "AND (NEW.fidelity IS NULL OR NEW.fidelity IN ('', 'face', 'body')) "
            "AND (NEW.train_type IS NULL OR NEW.train_type IN "
            "('zimage', 'krea', 'sdxl', 'flux', 'flux2klein'))")
        + _guard_triggers(
            'face_dataset_image',
            "NEW.dataset_id IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM face_dataset WHERE id = NEW.dataset_id) "
            "AND NEW.status IN ('pending', 'keep', 'reject', 'failed', 'trashed') "
            "AND NEW.source IN ('generated', 'import', 'upload') "
            "AND (NEW.anchor_decision IS NULL OR NEW.anchor_decision IN "
            "('', 'auto', 'pinned', 'excluded')) "
            "AND (NEW.training_usefulness IS NULL OR NEW.training_usefulness IN "
            "('green', 'amber', 'red')) "
            "AND (NEW.coverage_value IS NULL OR NEW.coverage_value IN "
            "('green', 'amber', 'unknown')) "
            "AND (NEW.framing IS NULL OR NEW.framing IN "
            "('face', 'bust', 'body', 'back', 'unknown')) "
            "AND (NEW.watermark_state IS NULL OR NEW.watermark_state IN "
            "('none', 'detected', 'dismissed', 'cleaned', 'failed')) "
            "AND (NEW.parent_image_id IS NULL OR EXISTS "
            "(SELECT 1 FROM face_dataset_image WHERE id = NEW.parent_image_id "
            "AND dataset_id = NEW.dataset_id)) "
            "AND (NEW.duplicate_of_id IS NULL OR EXISTS "
            "(SELECT 1 FROM face_dataset_image WHERE id = NEW.duplicate_of_id "
            "AND dataset_id = NEW.dataset_id))")
        + _guard_triggers(
            'lora_test_image',
            "NEW.dataset_id IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM face_dataset WHERE id = NEW.dataset_id) "
            "AND NEW.status IN ('pending', 'done', 'failed', 'cancelled') "
            "AND NEW.rating IN (-1, 0, 1)")
        + _guard_triggers(
            'image_generation_queue',
            "NEW.status IN ('pending', 'processing', 'sent_to_comfy', "
            "'completed', 'failed', 'cancelled') AND NEW.retry_count >= 0")
        + _guard_triggers(
            'background_job',
            "NEW.state IN ('pending', 'running', 'done', 'error', "
            "'cancelled', 'interrupted') AND NEW.attempts >= 1")
        + _guard_triggers(
            'cloud_training_run',
            "NEW.dataset_id IS NOT NULL AND NEW.status IN "
            "('preparing', 'provisioning', 'uploading', "
            "'training', 'downloading', 'terminating', 'done', 'stopped', "
            "'error', 'error_pod_kept') "
            "AND (NEW.price_per_hour IS NULL OR NEW.price_per_hour >= 0)")
        + _guard_triggers(
            'training_run_record',
            "NEW.dataset_id IS NOT NULL AND NEW.family IN "
            "('zimage', 'krea', 'sdxl', 'flux', 'flux2klein') "
            "AND NEW.source IN ('local', 'cloud', 'legacy') "
            "AND NEW.version >= 1 AND (NEW.steps IS NULL OR NEW.steps >= 0)")
        + _guard_triggers(
            'training_preset',
            "NEW.train_type IN ('zimage', 'krea', 'sdxl', 'flux', 'flux2klein')")
        + [
            'CREATE TRIGGER IF NOT EXISTS trg_face_dataset_image_links_on_delete '
            'BEFORE DELETE ON face_dataset_image BEGIN '
            'UPDATE face_dataset_image SET parent_image_id = NULL '
            'WHERE parent_image_id = OLD.id; '
            'UPDATE face_dataset_image SET duplicate_of_id = NULL '
            'WHERE duplicate_of_id = OLD.id; END',
        ]
    ),
    8: (
        'CREATE TRIGGER IF NOT EXISTS trg_dataset_revision_image_insert '
        'AFTER INSERT ON face_dataset_image BEGIN '
        'UPDATE face_dataset SET revision = COALESCE(revision, 0) + 1, '
        'updated_at = CURRENT_TIMESTAMP WHERE id = NEW.dataset_id; END',
        'CREATE TRIGGER IF NOT EXISTS trg_dataset_revision_image_update '
        'AFTER UPDATE ON face_dataset_image BEGIN '
        'UPDATE face_dataset SET revision = COALESCE(revision, 0) + 1, '
        'updated_at = CURRENT_TIMESTAMP WHERE id = NEW.dataset_id; '
        'UPDATE face_dataset SET revision = COALESCE(revision, 0) + 1, '
        'updated_at = CURRENT_TIMESTAMP WHERE id = OLD.dataset_id '
        'AND OLD.dataset_id != NEW.dataset_id; END',
        'CREATE TRIGGER IF NOT EXISTS trg_dataset_revision_image_delete '
        'AFTER DELETE ON face_dataset_image BEGIN '
        'UPDATE face_dataset SET revision = COALESCE(revision, 0) + 1, '
        'updated_at = CURRENT_TIMESTAMP WHERE id = OLD.dataset_id; END',
    ),
    11: (
        'CREATE INDEX IF NOT EXISTS ix_lora_test_image_training_run_record_id '
        'ON lora_test_image (training_run_record_id)',
    ),
    12: tuple(
        f'CREATE TRIGGER IF NOT EXISTS trg_face_dataset_coverage_integrity_{operation.lower()} '
        f'BEFORE {operation} ON face_dataset '
        "WHEN NOT (NEW.coverage_profile IS NULL OR NEW.coverage_profile IN "
        "('', 'strict', 'balanced', 'experimental')) BEGIN "
        "SELECT RAISE(ABORT, 'integrity constraint failed: face_dataset coverage policy'); END"
        for operation in ('INSERT', 'UPDATE')
    ),
}


def _backup_database_before_migration() -> Path | None:
    database = db.engine.url.database
    if not database or database == ':memory:':
        return None
    source = Path(database)
    if not source.is_file():
        return None
    backup_dir = source.parent / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        try:
            os.chmod(backup_dir, 0o700)
        except OSError:
            pass
    target = backup_dir / (
        f'{source.stem}-pre-migration-{datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")}.db')
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    if os.name != 'nt':
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    return target


def _database_has_pending_migrations() -> bool:
    """Inspect the existing file before ``create_all`` mutates its schema."""
    database = db.engine.url.database
    if not database or database == ':memory:' or not Path(database).is_file():
        return False
    expected = {version for version, _name, _additions in _MIGRATIONS}
    try:
        with sqlite3.connect(database) as connection:
            present = {
                int(row[0]) for row in connection.execute(
                    'SELECT version FROM schema_migration').fetchall()
            }
    except (sqlite3.Error, TypeError, ValueError):
        # A legacy database has no ledger yet; it needs the full pre-change backup.
        return True
    return not expected.issubset(present)


def _storage_is_writable(directory: Path) -> bool:
    """Exercise the same create/delete capability runtime jobs require."""
    probe = None
    try:
        descriptor, probe = tempfile.mkstemp(prefix='.readiness-', dir=directory)
        os.close(descriptor)
        os.unlink(probe)
        probe = None
        return True
    except OSError:
        return False
    finally:
        if probe:
            try:
                os.unlink(probe)
            except OSError:
                pass


def _apply_schema_migrations(backup_path=None):
    """Apply every pending migration or fail startup with an actionable error."""
    from sqlalchemy import text
    db.session.execute(text(
        'CREATE TABLE IF NOT EXISTS schema_migration ('
        'version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)'))
    db.session.commit()
    applied = {row[0] for row in db.session.execute(
        text('SELECT version FROM schema_migration')).all()}
    for version, name, additions in _MIGRATIONS:
        if version in applied:
            continue
        try:
            statements = _MIGRATION_SQL.get(version, ())
            missing = []
            for table, column, column_type in additions:
                existing = {row[1] for row in db.session.execute(
                    text(f'PRAGMA table_info({table})'))}
                if column not in existing:
                    missing.append((table, column, column_type))
            if (missing or statements) and backup_path is None:
                backup_path = _backup_database_before_migration()
            for table, column, column_type in missing:
                db.session.execute(text(
                    f'ALTER TABLE {table} ADD COLUMN {column} {column_type}'))
            for statement in statements:
                db.session.execute(text(statement))
            db.session.execute(text(
                'INSERT INTO schema_migration(version, name, applied_at) '
                'VALUES (:version, :name, :applied_at)'), {
                    'version': version, 'name': name,
                    'applied_at': datetime.now(timezone.utc).isoformat(),
                })
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            backup = f' Backup: {backup_path}' if backup_path else ''
            raise RuntimeError(
                f'database migration {version} ({name}) failed; startup stopped '
                f'to protect the dataset.{backup}') from exc

def create_app(config_object=None):
    app = Flask(__name__, static_folder=None)
    data_dir = Path(os.environ.get('LDS_DATA_DIR', str(cfg.REPO_ROOT / 'data')))
    data_dir.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        try:
            data_dir.chmod(0o700)
        except OSError:
            pass
    try:
        max_upload_mb = max(64, int(os.environ.get('LDS_MAX_UPLOAD_MB', '2048')))
    except (TypeError, ValueError):
        max_upload_mb = 2048
    app.config.update(
        SECRET_KEY=cfg.secret_key(),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{data_dir / 'studio.db'}",
        SQLALCHEMY_ENGINE_OPTIONS={'connect_args': {'check_same_thread': False}},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict',
        # Large local corpora and portable backups are intentionally supported.
        # FileStorage spools large parts to disk; the import route consumes them
        # in small batches instead of materialising the whole request as bytes.
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
    )
    app.config.update(config_object or {})

    # File logging (skipped under TESTING): every module logger flows into
    # data/app.log (rotating, 2 MB x 2) so the in-app log viewer — and a novice
    # reporting a bug — always has something to read, launcher or not (the
    # portable launcher additionally captures raw stdout into data/server.log).
    if not app.config.get('TESTING'):
        import logging
        from logging.handlers import RotatingFileHandler
        root = logging.getLogger()
        log_path = str(data_dir / 'app.log')
        if not any(isinstance(h, RotatingFileHandler)
                   and getattr(h, 'baseFilename', '') == os.path.abspath(log_path)
                   for h in root.handlers):
            fh = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024,
                                     backupCount=2, encoding='utf-8')
            if os.name != 'nt':
                try:
                    Path(log_path).chmod(0o600)
                except OSError:
                    pass
            fh.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s %(name)s: %(message)s'))
            fh.setLevel(logging.INFO)
            root.addHandler(fh)
            if root.level > logging.INFO or root.level == logging.NOTSET:
                root.setLevel(logging.INFO)

    db.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        @event.listens_for(db.engine, 'connect')
        def _sqlite_pragmas(dbapi_con, _):
            cur = dbapi_con.cursor()
            cur.execute('PRAGMA journal_mode=WAL')
            cur.execute('PRAGMA busy_timeout=5000')
            cur.execute('PRAGMA synchronous=NORMAL')
            cur.execute('PRAGMA foreign_keys=ON')
            cur.close()
        from . import models  # noqa: F401
        # ``create_all`` itself creates tables introduced by migrations whose
        # SQL body is intentionally empty. Back up an existing, behind schema
        # before that call so "pre-migration" genuinely means pre-mutation.
        migration_backup = (_backup_database_before_migration()
                            if _database_has_pending_migrations() else None)
        db.create_all()
        _apply_schema_migrations(backup_path=migration_backup)
        if os.name != 'nt':
            # The database carries local image metadata, provider auth tokens,
            # job paths, and run history. Existing databases and SQLite's WAL
            # companions must be owner-only.
            database_path = Path(db.engine.url.database or '')
            for private_path in (
                    database_path,
                    Path(f'{database_path}-wal'),
                    Path(f'{database_path}-shm')):
                if private_path.is_file():
                    try:
                        private_path.chmod(0o600)
                    except OSError:
                        pass
        # The reconstruction workflow used to allow several independently kept
        # children for one source. Normalize those legacy groups before any worker
        # or API request can observe them under the new exclusive-pair contract.
        from .services.face_dataset_service import normalize_legacy_image_improvement_rows
        normalize_legacy_image_improvement_rows()
        # Vision requests are process-local, while their mutual-exclusion flag is
        # persisted in SQLite. A killed captioning request therefore cannot still
        # be running after boot; clear its stale flag immediately instead of
        # leaving the restarted app stuck on "GPU busy" until the TTL expires.
        from .gpu_window import recover_stale_vision_window
        recover_stale_vision_window()
        # Request-owned daemon threads do not survive a process restart. Close
        # their durable ledger rows and provider-generation placeholders before
        # the SPA can mistake them for work that is still running.
        from .services.background_jobs import recover_interrupted
        from .services.face_dataset_service import recover_interrupted_api_generations
        recover_interrupted()
        recover_interrupted_api_generations()

    from .routes import register_blueprints
    register_blueprints(app, csrf)

    # Correlate browser errors, API responses and server logs without exposing
    # internal stack traces. A caller may propagate its own safe request id;
    # malformed values are ignored so log records cannot be injected.
    @app.before_request
    def _begin_request_trace():
        supplied = request.headers.get('X-Request-ID', '')
        g.request_id = (supplied if re.fullmatch(r'[A-Za-z0-9._-]{8,64}', supplied)
                        else uuid.uuid4().hex)
        g.request_started = perf_counter()

    # Non-loopback clients must present the access token (run.py generates one
    # when the bind is opened) — without this, `server.host: 0.0.0.0` would hand
    # the whole LAN the API keys, the GPU and the datasets. Loopback = untouched.
    from .netguard import install_network_guard
    install_network_guard(app)

    @app.get('/api/health')
    def health():
        return {'ok': True}

    @app.get('/api/health/live')
    def health_live():
        """Process liveness only: no dependency checks and never blocks."""
        return {'ok': True, 'status': 'live'}

    @app.get('/api/health/ready')
    def health_ready():
        """Readiness for launchers/orchestrators: schema, storage and UI ready."""
        components = {
            'database': {'ok': False},
            'storage': {'ok': _storage_is_writable(data_dir)},
            'frontend': {'ok': (FRONTEND_DIST / 'index.html').is_file()},
        }
        try:
            db.session.execute(text('SELECT 1'))
            applied_versions = set(db.session.execute(
                text('SELECT version FROM schema_migration')).scalars())
            expected_versions = {version for version, _, _ in _MIGRATIONS}
            missing_versions = sorted(expected_versions - applied_versions)
            unexpected_versions = sorted(applied_versions - expected_versions)
            components['database'] = {
                'ok': not missing_versions and not unexpected_versions,
                'schema_version': max(applied_versions, default=0),
                'expected_schema_version': max(expected_versions),
                'missing_migrations': missing_versions,
                'unexpected_migrations': unexpected_versions,
            }
        except Exception:
            db.session.rollback()
            app.logger.exception('readiness database check failed request_id=%s', g.request_id)
        ready = all(component['ok'] for component in components.values())
        return jsonify({'ok': ready, 'status': 'ready' if ready else 'not_ready',
                        'components': components}), 200 if ready else 503

    @app.errorhandler(CSRFError)
    def _csrf_error(exc):
        response = jsonify({
            'ok': False,
            'error': 'session token is missing or expired',
            'error_code': 'csrf_failed',
            'request_id': g.get('request_id'),
        })
        response.status_code = 400
        response.headers['X-CSRF-Error'] = '1'
        return response

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if not request.path.startswith('/api'):
            return exc
        return jsonify({
            'ok': False,
            'error': exc.description or exc.name,
            'error_code': f'http_{exc.code}',
            'request_id': g.get('request_id'),
        }), exc.code

    @app.errorhandler(Exception)
    def _unhandled_error(exc):
        request_id = g.get('request_id')
        app.logger.exception('unhandled request error request_id=%s path=%s',
                             request_id, request.path)
        return jsonify({
            'ok': False,
            'error': 'internal server error',
            'error_code': 'internal_error',
            'request_id': request_id,
        }), 500

    @app.get('/api/csrf-token')
    def csrf_token():
        from flask_wtf.csrf import generate_csrf
        return jsonify({'csrf_token': generate_csrf()})

    @app.get('/')
    def index():
        if not FRONTEND_DIST.exists():
            return jsonify({'error': 'frontend not built — run pnpm run build in frontend/'}), 503
        # The csrf_token cookie is (re)planted by the after_request hook below —
        # which covers '/' AND every /api response — so a SPA session can no longer
        # outlive its token (see _refresh_csrf_cookie for the full rationale).
        return send_from_directory(FRONTEND_DIST, 'index.html')

    @app.get('/assets/<path:filename>')
    def assets(filename):
        return send_from_directory(FRONTEND_DIST / 'assets', filename)

    @app.after_request
    def _refresh_csrf_cookie(resp):
        # Flask-WTF's CSRF token is time-limited (WTF_CSRF_TIME_LIMIT, default 1 h).
        # Historically the cookie was planted ONLY on GET / — so a SPA tab left open
        # past that limit kept echoing a now-expired token, and every Save/Test POST
        # came back as a cryptic HTML 400 that only a hard refresh cleared. Re-plant a
        # freshly-timestamped token on the app shell and on every /api response (static
        # assets are skipped — pure noise): any request the SPA makes keeps the cookie
        # alive, and even the CSRF-rejection 400 itself carries a fresh cookie so the
        # client's one-shot retry lands on a valid token with no reload. This also
        # covers the Vite dev server, which proxies only /api (Flask never sees GET /,
        # so the cookie was never planted there at all).
        #
        # httponly stays False (the default) so the SPA can read the cookie and echo
        # it back in the X-CSRFToken header; samesite='Lax' mirrors the original
        # GET / cookie; no `secure` flag (the app is reached over plain http on
        # loopback/LAN). after_request runs BEFORE save_session, so a first-ever
        # session gets its csrf secret persisted alongside this cookie.
        if request.path == '/' or request.path.startswith('/api'):
            from flask_wtf.csrf import generate_csrf
            resp.set_cookie('csrf_token', generate_csrf(), samesite='Lax')
        return resp

    @app.after_request
    def _finish_request_trace(resp):
        request_id = g.get('request_id') or uuid.uuid4().hex
        elapsed_ms = max(0, (perf_counter() - g.get('request_started', perf_counter())) * 1000)
        resp.headers['X-Request-ID'] = request_id
        resp.headers['Server-Timing'] = f'app;dur={elapsed_ms:.1f}'

        # Route handlers historically expose a flat string `error`; preserve it
        # for existing clients while attaching one consistent structured detail
        # object to every JSON error response.
        if request.path.startswith('/api') and resp.status_code >= 400 and resp.is_json:
            payload = resp.get_json(silent=True)
            if isinstance(payload, dict):
                message = payload.get('error') or payload.get('message') or resp.status
                if not isinstance(message, str):
                    message = str(message)
                code = payload.get('error_code') or payload.get('code') or f'http_{resp.status_code}'
                payload.setdefault('ok', False)
                payload.setdefault('error_code', code)
                payload.setdefault('request_id', request_id)
                payload.setdefault('error_detail', {
                    'code': code,
                    'message': message,
                    'request_id': request_id,
                })
                resp.set_data(app.json.dumps(payload))
                resp.content_type = 'application/json'
            log = app.logger.warning if resp.status_code >= 500 else app.logger.info
            log('api_request_failed request_id=%s method=%s path=%s status=%s duration_ms=%.1f',
                request_id, request.method, request.path, resp.status_code, elapsed_ms)
        return resp

    if not app.config.get('TESTING'):
        _start_workers(app)
    return app

def _start_workers(app):
    """Boot background machinery. Idempotent; nothing GPU-ish is required."""
    from .job_queue import queue_manager
    queue_manager.init_app(app)
    queue_manager.start()
    try:
        from .services.lora_training import start_training_scheduler
        start_training_scheduler(app)
    except ImportError:
        pass  # phase(<3): training service not lifted yet

    from .services.checkpoint_registry import start_legacy_backfill
    start_legacy_backfill(app)

    import threading
    from .services import cloud_training
    cloud_training.start_reconciler(app)
    threading.Thread(target=cloud_training.boot_recover, args=(app,),
                     daemon=True, name='cloud-boot-recover').start()
