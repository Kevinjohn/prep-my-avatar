from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .core import _json_dump, load_json, load_records, write_reports, write_selection_csv


_REVIEW_LOCK = threading.Lock()
_REVIEW_FIELDS = {"status", "caption", "training_usefulness", "coverage_value", "special", "manual"}
_RATINGS = {"green", "amber", "red"}


def _validate_review_patch(out_dir: Path, image_id: object, payload: dict[str, object]) -> None:
    manifest = load_json(out_dir / "manifest.json", {})
    known_ids = {record.get("id") for record in manifest.get("records", []) if isinstance(record, dict)}
    if not isinstance(image_id, str) or image_id not in known_ids:
        raise ValueError("id must identify a record in this run")
    unknown = set(payload) - _REVIEW_FIELDS
    if unknown:
        raise ValueError(f"Unknown review fields: {', '.join(sorted(unknown))}")
    for field in ("status", "training_usefulness", "coverage_value"):
        if field in payload and payload[field] not in _RATINGS:
            raise ValueError(f"{field} must be green, amber, or red")
    if "caption" in payload and (not isinstance(payload["caption"], str) or len(payload["caption"]) > 20_000):
        raise ValueError("caption must be a string of at most 20000 characters")
    if "special" in payload and payload["special"] not in {None, "holdout"}:
        raise ValueError("special must be holdout or null")
    if "manual" in payload and not isinstance(payload["manual"], dict):
        raise ValueError("manual must be an object")


VIEWER_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Avatar Prep Review</title>
  <style>
    :root { color-scheme: light; --ink:#17202a; --muted:#68737d; --line:#dfe5e9; --panel:#fff; --bg:#f4f6f7; --green:#17834b; --amber:#a56600; --red:#bd2d3b; }
    * { box-sizing:border-box; }
    body { margin:0; font:14px/1.45 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); }
    header { position:sticky; top:0; z-index:4; padding:18px 24px; background:rgba(255,255,255,.94); backdrop-filter:blur(10px); border-bottom:1px solid var(--line); }
    h1 { margin:0 0 4px; font-size:22px; }
    h2 { margin:0; font-size:16px; }
    .subtle { color:var(--muted); }
    .summary { display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }
    .stat { min-width:120px; padding:10px 12px; border:1px solid var(--line); border-radius:10px; background:var(--panel); }
    .stat strong { display:block; font-size:21px; }
    .toolbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:14px; }
    button, select, input, textarea { font:inherit; }
    button, select { border:1px solid #cbd3d8; border-radius:7px; background:#fff; padding:7px 10px; cursor:pointer; }
    button:hover { border-color:#68737d; }
    main { max-width:1600px; margin:0 auto; padding:24px; }
    .notice { padding:12px 14px; border-left:4px solid #d89a22; background:#fff8e8; border-radius:6px; margin-bottom:18px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(480px,1fr)); gap:16px; }
    .card { border:1px solid var(--line); border-radius:12px; overflow:hidden; background:#fff; box-shadow:0 2px 8px rgba(23,32,42,.05); }
    .card-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; padding:12px 14px; border-bottom:1px solid var(--line); }
    .card-head strong { overflow-wrap:anywhere; }
    .rag { display:inline-flex; align-items:center; gap:6px; white-space:nowrap; font-weight:700; text-transform:uppercase; font-size:11px; letter-spacing:.04em; }
    .dot { width:11px; height:11px; border-radius:50%; display:inline-block; }
    .green .dot { background:var(--green); } .amber .dot { background:var(--amber); } .red .dot { background:var(--red); }
    .image-row { display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:10px; background:#eef1f2; }
    figure { margin:0; min-width:0; }
    figure img { display:block; width:100%; aspect-ratio:1/1; object-fit:contain; background:#dce2e5; border-radius:7px; }
    figcaption { margin-top:4px; color:var(--muted); font-size:11px; }
    .details { padding:12px 14px; }
    .chips { display:flex; flex-wrap:wrap; gap:5px; margin:8px 0; }
    .chip { border:1px solid var(--line); border-radius:999px; padding:3px 7px; font-size:11px; background:#f8fafb; }
    .metrics { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin:9px 0; }
    .metric { border:1px solid var(--line); border-radius:7px; padding:6px 8px; }
    .metric span { display:block; color:var(--muted); font-size:11px; }
    .metric strong { font-size:15px; }
    .reasons { margin:8px 0; padding-left:18px; color:#5e3d00; }
    textarea { width:100%; min-height:65px; resize:vertical; border:1px solid #cbd3d8; border-radius:7px; padding:8px; }
    .actions { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
    .actions button[data-status="green"] { color:var(--green); } .actions button[data-status="amber"] { color:var(--amber); } .actions button[data-status="red"] { color:var(--red); }
    .save { background:#17202a; color:#fff; border-color:#17202a; }
    .empty { padding:30px; color:var(--muted); text-align:center; }
    @media (max-width:650px) { main { padding:12px; } .grid { grid-template-columns:1fr; } .card { min-width:0; } }
  </style>
</head>
<body>
  <header>
    <h1>Avatar Prep Review</h1>
    <div class="subtle" id="subtitle">Loading manifest…</div>
    <div class="summary" id="summary"></div>
    <div class="toolbar">
      <label>Show <select id="filter"><option value="all">all</option><option value="green">green</option><option value="amber">amber</option><option value="red">red</option></select></label>
      <label>Search <input id="search" placeholder="filename or reason"></label>
      <button id="refresh">Refresh</button>
    </div>
  </header>
  <main>
    <div class="notice" id="notice">This is a local review. Green/amber/red ratings are recommendations, not a substitute for inspecting the face and crop.</div>
    <div class="grid" id="grid"></div>
  </main>
<script>
let manifest = null;
let review = {};
let page = 0;
const pageSize = 100;
const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const label = value => String(value ?? 'unknown').replaceAll('_',' ');
const statusText = value => value === 'green' ? 'green' : value === 'red' ? 'red' : 'amber';
const pathFor = value => String(value ?? '').replaceAll('\\','/').split('/').map(encodeURIComponent).join('/');

async function load() {
  manifest = await fetch('/manifest.json?ts=' + Date.now()).then(r => r.json());
  review = await fetch('/review.json?ts=' + Date.now()).then(r => r.json());
  document.getElementById('subtitle').textContent = `${manifest.records.length} images · token ${manifest.token}`;
  renderSummary(); renderGrid();
}

function effective(record) {
  const patch = review[record.id] || {};
  return Object.assign({}, record, patch, {annotations:Object.assign({}, record.annotations, patch.annotations || {})});
}

function renderSummary() {
  const records = manifest.records.map(effective);
  const counts = ['green','amber','red'].map(s => [s, records.filter(r => statusText(r.status) === s).length]);
  const unknownViews = records.filter(r => (r.annotations || {}).view === 'unknown').length;
  document.getElementById('summary').innerHTML = counts.map(([s,n]) => `<div class="stat ${s}"><strong>${n}</strong><span class="rag"><i class="dot"></i>${s}</span></div>`).join('') + `<div class="stat"><strong>${unknownViews}</strong><span class="subtle">unknown views</span></div>`;
}

function renderGrid() {
  const filter = document.getElementById('filter').value;
  const term = document.getElementById('search').value.trim().toLowerCase();
  const records = manifest.records.map(effective).filter(r => {
    const haystack = [r.source_name, ...(r.reasons || []), JSON.stringify(r.annotations || {})].join(' ').toLowerCase();
    return (filter === 'all' || statusText(r.status) === filter) && (!term || haystack.includes(term));
  });
  const pageCount = Math.max(1, Math.ceil(records.length / pageSize));
  page = Math.min(page, pageCount - 1);
  const visible = records.slice(page * pageSize, (page + 1) * pageSize);
  const controls = records.length > pageSize ? `<div class="empty"><button onclick="changePage(-1)" ${page === 0 ? 'disabled' : ''}>Previous</button> Page ${page + 1} of ${pageCount} <button onclick="changePage(1)" ${page + 1 === pageCount ? 'disabled' : ''}>Next</button></div>` : '';
  document.getElementById('grid').innerHTML = records.length ? visible.map(card).join('') + controls : '<div class="empty">No images match this filter.</div>';
}
function changePage(delta) { page += delta; renderGrid(); window.scrollTo({top:0, behavior:'smooth'}); }

function card(record) {
  const status = statusText(record.status);
  const a = record.annotations || {};
  const chips = ['view','framing','expression','lighting','background','face_visibility'].map(k => `<span class="chip">${esc(k)}: ${esc(label(a[k]))}</span>`).join('');
  const values = value => Array.isArray(value) ? value : value ? [value] : [];
  const clothing = [...values(a.clothing), ...values(a.accessories)].map(v => `<span class="chip">${esc(label(v))}</span>`).join('');
  const reasons = (record.reasons || []).map(v => `<li>${esc(v)}</li>`).join('');
  const special = record.special ? `<span class="chip">${esc(label(record.special))}</span>` : '';
  const original = pathFor(record.original_path);
  const cropName = record.primary_crop || 'square';
  const cropValue = (record.crops || {})[cropName] || (record.crops || {}).square;
  const crop = pathFor(cropValue);
  return `<article class="card" data-id="${esc(record.id)}">
    <div class="card-head"><div><strong>${esc(record.source_name)}</strong><div class="subtle">${record.width || '?'} × ${record.height || '?'} · ${Math.round((record.file_size || 0)/1024)} KB</div></div><span class="rag ${status}"><i class="dot"></i>${status}</span></div>
    <div class="image-row"><figure><img loading="lazy" src="/${original}" alt="Original ${esc(record.source_name)}"><figcaption>Original</figcaption></figure>${cropValue ? `<figure><img loading="lazy" src="/${crop}" alt="Proposed ${esc(label(cropName))} crop"><figcaption>Proposed ${esc(label(cropName))} crop</figcaption></figure>` : '<div class="notice">Crop unavailable because image processing failed.</div>'}</div>
    <div class="details"><div class="chips">${special}${chips}${clothing}</div>
      <div class="metrics"><div class="metric"><span>Sharpness</span><strong>${record.metrics?.sharpness ?? 0}</strong></div><div class="metric"><span>Exposure</span><strong>${record.metrics?.exposure ?? 0}</strong></div><div class="metric"><span>Resolution</span><strong>${record.metrics?.resolution ?? 0}</strong></div></div>
      ${reasons ? `<ul class="reasons">${reasons}</ul>` : '<div class="subtle">No warnings from automated analysis.</div>'}
      <label class="subtle" for="caption-${esc(record.id)}">Caption</label><textarea id="caption-${esc(record.id)}">${esc(record.caption || '')}</textarea>
      <div class="actions"><button data-status="green" onclick="setStatus('${esc(record.id)}','green')">Training green</button><button data-status="amber" onclick="setStatus('${esc(record.id)}','amber')">Amber / review</button><button data-status="red" onclick="setStatus('${esc(record.id)}','red')">Do not train</button><button onclick="setSpecial('${esc(record.id)}','holdout')">Holdout</button><button onclick="setSpecial('${esc(record.id)}',null)">Clear holdout</button><button class="save" onclick="saveCaption('${esc(record.id)}')">Save caption</button></div>
    </div></article>`;
}

async function update(id, patch) {
  const response = await fetch('/api/review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id, ...patch})});
  if (!response.ok) { alert('Could not save review decision'); return; }
  await load();
}
function captionFor(id) { return document.getElementById('caption-' + id).value; }
function setStatus(id, status) { update(id, {status, training_usefulness:status, caption:captionFor(id)}); }
function setSpecial(id, special) { update(id, {special, caption:captionFor(id)}); }
function saveCaption(id) { const value = document.getElementById('caption-' + id).value; update(id, {caption:value}); }
document.getElementById('filter').addEventListener('change', () => { page = 0; renderGrid(); });
let searchTimer;
document.getElementById('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page = 0; renderGrid(); }, 150); });
document.getElementById('refresh').addEventListener('click', load);
load().catch(error => { document.getElementById('notice').textContent = 'Could not load the manifest: ' + error; });
</script>
</body>
</html>
'''


def write_viewer(out_dir: Path) -> None:
    report_dir = out_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "index.html").write_text(VIEWER_HTML, encoding="utf-8")


class ReviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, out_dir: Path, **kwargs):
        self.out_dir = out_dir
        super().__init__(*args, directory=directory, **kwargs)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/review":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        # Defense in depth (DBR-0014): the viewer is a localhost-only tool with
        # no session layer, so reject cross-origin POSTs (e.g. a malicious page
        # in the user's browser firing requests at the local port).
        origin = self.headers.get("Origin")
        if origin:
            try:
                origin_host = urlparse(origin).hostname or ""
            except ValueError:
                origin_host = ""
            allowed_hosts = {"127.0.0.1", "localhost", "::1"}
            if origin_host not in allowed_hosts:
                self.send_error(HTTPStatus.FORBIDDEN, "cross-origin requests are not allowed")
                return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64 * 1024:
                raise ValueError("review payload must be between 1 byte and 64 KiB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("review payload must be a JSON object")
            image_id = payload.pop("id")
            _validate_review_patch(self.out_dir, image_id, payload)
            with _REVIEW_LOCK:
                review_path = self.out_dir / "review.json"
                review = load_json(review_path, {})
                current = review.setdefault(image_id, {})
                current.update(payload)
                _json_dump(review_path, review)
                derived_updated = True
                try:
                    manifest, records = load_records(self.out_dir)
                    write_selection_csv(self.out_dir, records)
                    write_reports(self.out_dir, records, manifest.get("token", "pm_subject"))
                except Exception as exc:
                    derived_updated = False
                    print(f"[review] decision saved but derived reports could not be refreshed: {exc}")
            body = json.dumps({"ok": True, "derived_updated": derived_updated}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # Keep the local viewer alive and show a useful error.
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def log_message(self, format: str, *args) -> None:
        print("[review] " + format % args)


def serve(out_dir: Path, port: int = 8765) -> None:
    write_viewer(out_dir)

    def handler(*args, **kwargs):
        return ReviewHandler(*args, directory=str(out_dir), out_dir=out_dir, **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Review viewer: http://127.0.0.1:{port}/reports/index.html")
    print("Press Ctrl-C to stop the local viewer.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
