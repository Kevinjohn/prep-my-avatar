/**
 * Centralized API fetch client with global error interception via toast.
 */

let toastRef = null;

export function setToastRef(toast) {
  toastRef = toast;
}

export function getCsrfToken() {
  const match = document.cookie.match(/csrf_token=([^;]+)/);
  if (match) return decodeURIComponent(match[1]);
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta instanceof HTMLMetaElement ? meta.content : '';
}

export class ApiError extends Error {
  constructor(message, status, body = null, requestId = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.requestId = requestId;
  }
}

/* The single human, actionable message shown when a CSRF 400 survives the
   automatic retry — never the cryptic "HTTP 400". Shared so apiFetch and
   useDataset's local postJson word it identically. */
export const CSRF_EXPIRED_MESSAGE =
  'Session token expired — refresh the page (Ctrl+Shift+R) and try again.';

/* Flask-WTF rejects a stale/missing CSRF token with a 400 whose body is an HTML
   page, NOT one of our JSON error envelopes (which are always application/json).
   That content-type mismatch is the honest, body-safe signal to refresh + retry;
   a genuine 400 from our own handlers is application/json and is left untouched. */
function isCsrfRejection(res) {
  if (res.status !== 400) return false;
  if (res.headers.get('x-csrf-error') === '1') return true;
  const ct = res.headers.get('content-type') || '';
  return !ct.includes('application/json');
}

// A request carries an X-CSRFToken header only when it mutates state (our
// post/put/del/postForm helpers). Only those can be rejected for a stale token
// and only those are meaningful to replay — a bare GET never enters the retry.
/** @param {HeadersInit | undefined} headers */
function csrfHeaderName(headers) {
  return [...new Headers(headers).keys()].find((key) => key.toLowerCase() === 'x-csrftoken');
}

// Rebuild request options with a freshly-read CSRF token: the header for JSON
// bodies, plus the csrf_token field for FormData bodies (the generation path
// sends the token both ways). FormData is mutable, so it is reused in place.
/** @param {RequestInit} options */
function withFreshCsrf(options) {
  const token = getCsrfToken();
  const name = csrfHeaderName(options.headers) || 'X-CSRFToken';
  if (typeof FormData !== 'undefined' && options.body instanceof FormData) {
    options.body.set?.('csrf_token', token);
  }
  const headers = new Headers(options.headers);
  headers.set(name, token);
  return { ...options, headers };
}

/**
 * fetch() with ONE automatic CSRF recovery, shared by every JSON and FormData
 * caller. When a state-changing request comes back as a CSRF rejection (see
 * isCsrfRejection — the classic "SPA left open past WTF_CSRF_TIME_LIMIT" case),
 * refresh the token and replay the request exactly once with the fresh token.
 * The backend re-plants a fresh cookie on every response (including the 400
 * itself), and the light GET below is a belt-and-suspenders for any path that
 * somehow didn't. Returns the raw Response so both parsed-JSON and raw-Response
 * callers reuse the same recovery. Network errors propagate to the caller.
 */
/**
 * @param {RequestInfo | URL} url
 * @param {RequestInit} [options]
 */
export async function fetchWithCsrfRetry(url, options = {}) {
  /** @type {RequestInit} */
  const opts = { credentials: 'include', ...options };
  let res = await fetch(url, opts);
  if (isCsrfRejection(res) && csrfHeaderName(opts.headers)) {
    await refreshCsrfToken();
    res = await fetch(url, { credentials: 'include', ...withFreshCsrf(opts) });
  }
  return res;
}

export async function apiFetch(url, options = {}) {
  let res;
  try {
    res = await fetchWithCsrfRetry(url, options);
  } catch {
    toastRef?.error('Connection lost. Please check your network.');
    throw new Error('Network error');
  }

  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    let body = null;
    let parsed = false;
    try {
      body = await res.json();
      parsed = true;
      msg = (body && (body.error || body.detail || body.message)) || msg;
    } catch {}

    if (res.status === 400 && !parsed) {
      // A 400 whose body still isn't our JSON envelope after the retry above is
      // an unrecoverable CSRF rejection — surface the actionable message, not
      // the raw "HTTP 400".
      msg = CSRF_EXPIRED_MESSAGE;
    } else if (res.status === 401) {
      toastRef?.error('Session expired. Please log in again.');
    } else if (res.status === 429) {
      toastRef?.warning('Too many requests. Please wait a moment.');
    } else if (res.status >= 500) {
      toastRef?.error('Server error. Please try again later.');
    }

    // Carry the parsed error body so callers can read structured fields (e.g. a
    // 409's `studio_missing`) instead of just the flat message.
    throw new ApiError(msg, res.status, body,
      body?.request_id || res.headers.get('x-request-id') || null);
  }

  return res.json();
}

export const getJson = (url, options = {}) => apiFetch(url, options);

/** Raw response variant for downloads/streams. It keeps the same credentials,
 * CSRF retry and structured error contract as apiFetch without consuming a
 * successful body as JSON. */
export async function apiResponse(url, options = {}) {
  let res;
  try {
    res = await fetchWithCsrfRetry(url, options);
  } catch {
    toastRef?.error('Connection lost. Please check your network.');
    throw new Error('Network error');
  }
  if (res.ok) return res;
  let body = null;
  try { body = await res.clone().json(); } catch { /* non-JSON response */ }
  throw new ApiError(body?.error || body?.detail || body?.message || `HTTP ${res.status}`,
    res.status, body, body?.request_id || res.headers.get('x-request-id') || null);
}

/** Envelope-returning client for mutation-heavy screens. Unlike apiFetch it
 * never throws: callers always receive `{ok:false,error,status,...body}` and can
 * render domain-specific errors while sharing the same transport behavior. */
export async function safeJson(url, options = {}) {
  try {
    const res = await fetchWithCsrfRetry(url, options);
    let body = null;
    let parsed = false;
    try { body = await res.json(); parsed = true; } catch { /* proxy/empty body */ }
    if (!res.ok) {
      const fallback = (!parsed && res.status === 400)
        ? CSRF_EXPIRED_MESSAGE : `Server error (${res.status})`;
      return { ...(body || {}), ok: false, status: res.status,
        error: body?.error || body?.detail || body?.message || fallback };
    }
    return body || { ok: true };
  } catch (error) {
    return { ok: false, status: 0, error: error?.message || 'Network error' };
  }
}

export function safePostJson(url, body, isForm = false) {
  return safeJson(url, {
    method: 'POST',
    headers: isForm
      ? { 'X-CSRFToken': getCsrfToken() }
      : { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
    body: isForm ? body : JSON.stringify(body || {}),
  });
}

export function safeDeleteJson(url) {
  return safeJson(url, {
    method: 'DELETE',
    headers: { 'X-CSRFToken': getCsrfToken() },
  });
}

export function postJson(url, body) {
  return apiFetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
    },
    body: JSON.stringify(body),
  });
}

export function putJson(url, body) {
  return apiFetch(url, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
    },
    body: JSON.stringify(body),
  });
}

export function del(url) {
  return apiFetch(url, {
    method: 'DELETE',
    headers: { 'X-CSRFToken': getCsrfToken() },
  });
}

export function postForm(url, formData) {
  formData.append('csrf_token', getCsrfToken());
  return apiFetch(url, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() },
    body: formData,
  });
}

/**
 * Refresh the CSRF token (server regenerates `session['csrf_token']` and
 * resets the matching cookie). Used as a recovery step when a POST fails
 * with a CSRF-mismatch 400 (typical after the session was regenerated
 * server-side — e.g. Flask-Login's session_protection='strong').
 */
export async function refreshCsrfToken() {
  try {
    await fetch('/api/csrf-token', { credentials: 'include' });
  } catch { /* network errors handled by caller */ }
}

/**
 * POST a FormData body to a Flask endpoint that returns JSON, with the same
 * refresh-and-retry-once CSRF recovery as every other mutating call. Returns the
 * raw Response so callers can do their own status-based handling (the /generate /
 * /generate_edit call sites need the Response, not just JSON). Thin wrapper over
 * the shared fetchWithCsrfRetry — kept as a named export for those call sites.
 */
/**
 * @param {RequestInfo | URL} url
 * @param {FormData} formData
 * @param {{signal?: AbortSignal}} [options]
 */
export async function postFormWithCsrfRetry(url, formData, { signal } = {}) {
  formData.set?.('csrf_token', getCsrfToken());
  return fetchWithCsrfRetry(url, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() },
    body: formData,
    signal,
  });
}
