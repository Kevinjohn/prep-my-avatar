import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const panel = readFileSync(new URL('./RunComparisonPanel.jsx', import.meta.url), 'utf8');

test('legacy runs do not invent admission, override, or masking provenance', () => {
  assert.match(panel, /run\.preflight == null && run\.overrides == null\) return 'Not recorded'/);
  assert.match(panel, /run\.masked == null \? ' · mask not recorded'/);
  assert.match(panel, /overrides not recorded/);
});
