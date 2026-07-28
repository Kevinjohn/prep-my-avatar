import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (name) => readFileSync(new URL(name, import.meta.url), 'utf8');

test('LoRA lock controls include action and model identity', () => {
  const source = read('./ZImageLoraConfig.jsx');
  assert.match(source, /aria-label=\{`\$\{c\.locked \? 'Unlock' : 'Lock'\} strength for \$\{l\.displayName\}`\}/);
  assert.match(source, /normalizedConfig\(JSON\.parse/);
});

test('resolution selector exposes single-selection group semantics and keyboard movement', () => {
  const source = read('./ResolutionSelector.jsx');
  assert.match(source, /role="radiogroup" aria-label=\{label\}/);
  assert.match(source, /role="radio"/);
  assert.match(source, /aria-checked=\{selected\}/);
  assert.match(source, /ArrowRight/);
});

test('Klein reconciliation persists fallback and uses an unambiguous dependency', () => {
  const source = read('./Flux2KleinModelPicker.jsx');
  assert.match(source, /localStorage\.setItem\(STORAGE_KEY, valid\)/);
  assert.doesNotMatch(source, /models\.join\('\|'\)/);
});
