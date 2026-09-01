import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const workspace = readFileSync(new URL('./DatasetWorkspace.jsx', import.meta.url), 'utf8');
const hook = readFileSync(new URL('../../hooks/useDataset.js', import.meta.url), 'utf8');

test('ordinary re-caption uses exact protected counts and disables an all-asserted scope', () => {
  assert.match(workspace, /captionRewriteCounts\(images\)/);
  assert.match(workspace, /recaptionCounts\.rewrite - recaptionCounts\.blank/);
  assert.match(workspace, /Every existing caption is yours/);
  assert.match(workspace, /disabled=\{ds\.busy \|\| \(!recaptionableExisting && !replaceAsserted\)\}/);
});

test('asserted override is relevant-only, unchecked, reset, and doubly confirmed', () => {
  assert.match(workspace, /useState\(false\).*replaceAsserted|\[replaceAsserted, setReplaceAsserted\] = useState\(false\)/s);
  assert.match(workspace, /recaptionCounts\.asserted > 0/);
  assert.match(workspace, /Also replace captions I wrote/);
  assert.match(workspace, /checked=\{replaceAsserted\}/);
  assert.match(workspace, /setReplaceAsserted\(false\)/);
  assert.match(workspace, /Replace your captions too\?/);
  assert.match(workspace, /includeAsserted\) await ds\.recaption\(effCaptionMode, true, captionProvider\)/);
});

test('hook sends the asserted flag only for the confirmed override', () => {
  assert.match(hook, /const recaption = useCallback\(\(mode, includeAsserted = false,\s*provider = 'configured'\)/);
  assert.match(hook, /\.\.\.\(includeAsserted \? \{ include_asserted: true \} : \{\}\)/);
  assert.doesNotMatch(hook, /include_asserted:\s*includeAsserted/);
});
