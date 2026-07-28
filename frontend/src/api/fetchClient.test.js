import assert from 'node:assert/strict';
import test from 'node:test';

import { apiFetch, fetchWithCsrfRetry, safeJson } from './fetchClient.js';

globalThis.document = {
  cookie: 'csrf_token=old-token',
  querySelector: () => null,
};

function jsonResponse(value, init = {}) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

test('only an explicit CSRF rejection replays a mutation', async (t) => {
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push([url, options.method || 'GET']);
    if (url === '/api/csrf-token') return jsonResponse({ ok: true });
    return new Response('<h1>Bad request</h1>', {
      status: 400,
      headers: { 'content-type': 'text/html' },
    });
  };
  await fetchWithCsrfRetry('/api/jobs', {
    method: 'POST', headers: { 'X-CSRFToken': 'old-token' }, body: '{}',
  });
  assert.deepEqual(requests.map(([url]) => url), ['/api/jobs']);

  requests.length = 0;
  let mutationCalls = 0;
  globalThis.fetch = async (url, options = {}) => {
    requests.push([url, options.method || 'GET']);
    if (url === '/api/csrf-token') return jsonResponse({ ok: true });
    mutationCalls += 1;
    if (mutationCalls === 1) {
      return new Response('', { status: 400, headers: { 'x-csrf-error': '1' } });
    }
    return jsonResponse({ ok: true });
  };
  const response = await fetchWithCsrfRetry('/api/jobs', {
    method: 'POST', headers: { 'X-CSRFToken': 'old-token' }, body: '{}',
  });
  assert.equal(response.ok, true);
  assert.deepEqual(requests.map(([url]) => url),
    ['/api/jobs', '/api/csrf-token', '/api/jobs']);
  t.after(() => { delete globalThis.fetch; });
});

test('apiFetch leaves notification ownership to its caller', async (t) => {
  const notifications = [];
  globalThis.fetch = async () => jsonResponse({ error: 'broken' }, { status: 500 });
  try {
    await apiFetch('/api/failure');
  } catch (error) {
    notifications.push(`Could not complete request: ${error.message}`);
  }
  assert.deepEqual(notifications, ['Could not complete request: broken']);
  t.after(() => { delete globalThis.fetch; });
});

test('JSON clients preserve empty and falsy successful payloads', async (t) => {
  const cases = [false, 0, null, [], { ok: true }];
  for (const value of cases) {
    globalThis.fetch = async () => jsonResponse(value);
    assert.deepEqual(await apiFetch('/api/value'), value);
    globalThis.fetch = async () => jsonResponse(value);
    assert.deepEqual(await safeJson('/api/value'), value);
  }

  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await apiFetch('/api/empty'), null);
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await safeJson('/api/empty'), null);
  t.after(() => { delete globalThis.fetch; });
});
