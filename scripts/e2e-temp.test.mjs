import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { childExitCode, E2E_PREFIX, markOwned, removeOwned, scavengeStaleOwned } from './e2e-temp.mjs';

test('scavenging removes only stale marked E2E directories', () => {
  const root = mkdtempSync(join(tmpdir(), 'e2e-temp-test-'));
  try {
    const stale = join(root, `${E2E_PREFIX}stale`);
    const fresh = join(root, `${E2E_PREFIX}fresh`);
    const unowned = join(root, `${E2E_PREFIX}unowned`);
    mkdirSync(stale);
    mkdirSync(fresh);
    mkdirSync(unowned);
    markOwned(stale, 1_000);
    markOwned(fresh, 9_000);

    scavengeStaleOwned(root, 10_000, 5_000);

    assert.equal(existsSync(stale), false);
    assert.equal(existsSync(fresh), true);
    assert.equal(existsSync(unowned), true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('owned cleanup is idempotent and child failures remain non-successful', () => {
  const root = mkdtempSync(join(tmpdir(), 'e2e-temp-test-'));
  const owned = join(root, `${E2E_PREFIX}owned`);
  mkdirSync(owned);
  markOwned(owned);

  assert.equal(removeOwned(owned), true);
  assert.equal(removeOwned(owned), false);
  assert.equal(childExitCode(null, 'SIGTERM'), 143);
  assert.equal(childExitCode(null, null), 1);
  assert.equal(childExitCode(7, null), 7);
  rmSync(root, { recursive: true, force: true });
});
