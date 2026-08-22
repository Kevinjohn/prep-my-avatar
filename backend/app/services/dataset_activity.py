"""In-memory per-dataset batch-activity registry.

Long batch operations on a dataset — watermark detect/clean, caption/re-caption,
face analysis, framing classification — run server-side inside a request thread.
The UI's "in progress" indicator used to be React-local state, so reloading the
page lost it while the server kept working. This registry lets the dataset payload
advertise a live ``activity`` object the front-end can RESTORE on reload and poll
to completion.

Design notes
------------
* **In-memory ONLY (no DB).** A batch dies with the process; on restart the
  registry is empty, so the (now-dead) indicator correctly disappears — nothing to
  clean up, no phantom "in progress" persisted anywhere.
* **Thread-safe.** A single module lock guards the store; these batches run in
  request threads and two datasets can be worked in parallel.
* **Crash-proof.** ``begin``/``end`` are meant to be used with ``try/finally`` so a
  batch that raises never leaves a phantom entry. As a belt-and-braces safety net a
  per-entry TTL is purged on every read: even if ``end`` were somehow skipped, the
  indicator can never outlive ``_TTL_SECONDS``.
* **One indicator per dataset.** The GPU-exclusive vision window serializes GPU
  passes (including watermark cleaning when CUDA is selected); CPU passes are
  guarded client-side by the hook's single-flight ``wrap`` on this
  single-local-user app — so overlapping
  kinds don't happen in normal use. Should two ever overlap (e.g. two browser
  tabs firing a GPU and a CPU pass at once), ``get`` returns the most recently
  STARTED one; the UI restores a single indicator, which is acceptable.
"""
import itertools
import threading
import time

# Kinds the UI knows how to restore. Kept as a documented allow-list so a typo in a
# begin() call is easy to spot. NOTHING reads this tuple — not begin(), not a test:
# it is prose in a tuple's clothing, and the enforcement is the bare literals at the
# begin() call sites matching the ones the front-end switches on.
# 'generate' covers the ⚡ Generate-variations batch (Nano Banana /
# ChatGPT / Klein) — it keeps the Generate button (and every concurrent action)
# disabled for the WHOLE batch, not just the launch request.
KINDS = ('watermark_detect', 'watermark_clean', 'caption', 'recaption',
         'analyze_faces', 'classify', 'generate')

# Safety TTL: an entry not touched for this long is purged on read even if end()
# never ran (process alive but the batch thread died without unwinding). 30 min is
# far longer than any real batch on a local dataset.
_TTL_SECONDS = 30 * 60

_lock = threading.Lock()
# dataset_id -> { token -> {kind, done, total, started_at, _touched} }
_active: dict = {}
_counter = itertools.count(1)


def _mint(dataset_id, kind, total, now, wall_now, **extra):
    """Create one registry entry and return ``(token, entry)``. Caller holds ``_lock``.

    Both minting sites go through here because the entry's key set is a CONTRACT:
    ``get`` reads five of these keys back and ``_purge_stale`` reads ``_touched``.
    The token grammar is a contract too — ``_dsid_of`` parses the dataset id back
    out of it, so the format lives in exactly one place.
    """
    sequence = next(_counter)
    token = f'{dataset_id}:{kind}:{sequence}'
    entry = {'kind': kind, 'done': 0, 'total': int(total or 0),
             'started_at': wall_now, '_started_order': sequence, '_touched': now,
             **extra}
    _active.setdefault(dataset_id, {})[token] = entry
    return token, entry


def _drop(dataset_id, token):
    """Remove one token, and the dataset's bucket once it holds nothing.

    An empty bucket left behind would keep the dataset in ``_purge_stale``'s scan
    for ever. Caller holds ``_lock``."""
    bucket = _active.get(dataset_id)
    if bucket is None:
        return
    bucket.pop(token, None)
    if not bucket:
        _active.pop(dataset_id, None)


def _purge_stale(now):
    """Globally discard stale buckets using the monotonic activity clock."""
    for dataset_id, bucket in list(_active.items()):
        for token, entry in list(bucket.items()):
            if now - entry['_touched'] > _TTL_SECONDS:
                bucket.pop(token, None)
        if not bucket:
            _active.pop(dataset_id, None)


def begin(dataset_id, kind, total=0, detail=None, engine=None):
    """Register a new in-progress batch on ``dataset_id`` and return an opaque token
    to pass to ``progress``/``bump``/``end``. ``total`` is the number of items the
    batch will process (0 when not enumerable up front)."""
    wall_now = time.time()
    now = time.monotonic()
    with _lock:
        _purge_stale(now)
        token, entry = _mint(dataset_id, kind, total, now, wall_now)
        if detail:
            entry['detail'] = str(detail)
        if engine:
            entry['engine'] = str(engine).lower()
    return token


def progress(token, done=None, total=None, detail=None):
    """Set the item counter (and optionally the total) for a running batch.
    No-op on an unknown/None token (already ended or purged)."""
    now = time.monotonic()
    with _lock:
        _purge_stale(now)
        entry = _entry(token)
        if entry is None:
            return
        if done is not None:
            entry['done'] = int(done)
        if total is not None:
            entry['total'] = int(total)
        if detail is not None:
            entry['detail'] = str(detail)
        entry['_touched'] = now


def bump(token, n=1):
    """Increment the item counter by ``n`` — convenience for per-image loops.
    No-op on an unknown/None token."""
    now = time.monotonic()
    with _lock:
        _purge_stale(now)
        entry = _entry(token)
        if entry is None:
            return
        entry['done'] += n
        entry['_touched'] = now


def end(token):
    """Remove a batch's entry. Idempotent (safe on an unknown/None token) so a
    ``finally``-block ``end`` never raises even if the entry was already purged."""
    with _lock:
        _drop(_dsid_of(token), token)


def sync_pending(dataset_id, kind, pending, engine=None):
    """Reconcile a COUNT-tracked indicator of ``kind`` against a live in-flight
    total. Used where per-batch tracking isn't available — a Klein generate batch
    completes one job at a time on the job-queue monitor thread, and each
    completion callback holds only a ``job_id`` (no batch handle); completions can
    also be duplicated (retry) or bypassed entirely (Stop deletes the rows without
    a completion). So instead of a fragile per-batch job set we track the honest
    "how many are still in flight" number read straight from the DB:

    * ``pending > 0`` — ensure an entry exists, grow ``total`` to the high-water
      mark of items ever seen in flight, and set ``done = total - pending``.
    * ``pending <= 0`` — the batch is finished: clear the entry.

    Only ever touches the entry IT created (tagged ``_synced``), so it can coexist
    with a worker-owned ``begin``/``end`` entry of the same kind (e.g. an API batch)
    without corrupting it. Idempotent — safe to call on every enqueue and every
    completion. TTL purge (via ``get``) is the final safety net if a completion is
    lost and ``pending`` never reaches 0."""
    wall_now = time.time()
    now = time.monotonic()
    with _lock:
        _purge_stale(now)
        bucket = _active.get(dataset_id) or {}
        tok = next((t for t, e in bucket.items()
                    if e['kind'] == kind and e.get('_synced')), None)
        if pending <= 0:
            if tok:
                _drop(dataset_id, tok)
            return
        if tok is None:
            tok, entry = _mint(dataset_id, kind, pending, now, wall_now,
                               _peak=int(pending), _synced=True)
        else:
            entry = bucket[tok]
        if engine:
            entry['engine'] = str(engine).lower()
        entry['_peak'] = max(entry['_peak'], int(pending))
        entry['total'] = entry['_peak']
        entry['done'] = max(0, entry['_peak'] - int(pending))
        entry['_touched'] = now


def get(dataset_id):
    """Return the current activity on ``dataset_id`` as
    ``{kind, done, total, started_at}`` or ``None``. Purges TTL-expired entries
    first, so a leaked entry can never strand a phantom indicator. When several
    batches overlap, the most recently STARTED one is returned (see module note)."""
    now = time.monotonic()
    with _lock:
        _purge_stale(now)
        bucket = _active.get(dataset_id)
        if not bucket:
            return None
        entry = max(bucket.values(), key=lambda e: e['_started_order'])
        result = {'kind': entry['kind'], 'done': entry['done'],
                  'total': entry['total'], 'started_at': entry['started_at']}
        if entry.get('detail'):
            result['detail'] = entry['detail']
        if entry.get('engine'):
            result['engine'] = entry['engine']
        return result


def _entry(token):
    """The mutable entry dict for ``token``, or None. Caller holds ``_lock``."""
    return (_active.get(_dsid_of(token)) or {}).get(token)


def _dsid_of(token):
    try:
        return int(str(token).split(':', 1)[0])
    except (ValueError, AttributeError):
        return None


def reset():
    """Test helper: clear the whole registry between cases."""
    with _lock:
        _active.clear()
