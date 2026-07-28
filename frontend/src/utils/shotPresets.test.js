import test from 'node:test';
import assert from 'node:assert/strict';
import {
  SHOT_PRESETS_STORAGE_KEY,
  CUSTOM_SHOTS_STORAGE_KEY,
  ShotPresetValidationError,
  applyShotPreset,
  deleteShotPreset,
  loadShotPresets,
  loadCustomShots,
  persistCustomShots,
  renameShotPreset,
  saveShotPreset,
} from './shotPresets.js';

const storage = (value) => ({ getItem: () => value });
const custom = { id: 'custom_1', label: 'Custom pose', prompt: 'pose', framing: 'body' };

test('malformed or unknown stored payloads are ignored', () => {
  assert.deepEqual(loadShotPresets(storage('{broken')), []);
  assert.deepEqual(loadShotPresets(storage(JSON.stringify({ version: 99, presets: [{}] }))), []);
  assert.equal(SHOT_PRESETS_STORAGE_KEY, 'datasetCustomPresetsV1');
});

test('custom-shot storage migrates arrays and cleans malformed payloads', () => {
  assert.deepEqual(loadCustomShots(storage('{broken')), []);
  assert.deepEqual(loadCustomShots(storage('{}')), []);
  assert.deepEqual(loadCustomShots(storage(JSON.stringify([custom, null, { id: 'bad' }]))), [custom]);
  const writes = [];
  persistCustomShots({ setItem: (...args) => writes.push(args) }, [custom, { id: 'bad' }]);
  assert.equal(writes[0][0], CUSTOM_SHOTS_STORAGE_KEY);
  assert.deepEqual(JSON.parse(writes[0][1]), { version: 1, shots: [custom] });
});

test('save validates name, selection and duplicate names', () => {
  assert.throws(() => saveShotPreset([], '', ['a'], []), ShotPresetValidationError);
  assert.throws(() => saveShotPreset([], 'Empty', [], []), /selection/i);
  const saved = saveShotPreset([], 'My mix', ['a'], []);
  assert.throws(() => saveShotPreset(saved, ' my MIX ', ['b'], []), /already exists/i);
});

test('save snapshots selected custom shots and apply restores missing definitions', () => {
  const [preset] = saveShotPreset([], 'Portrait set', ['builtin_1', custom.id], [custom]);
  assert.deepEqual(preset.customShots, [custom]);
  assert.deepEqual(applyShotPreset(preset, []), {
    selectedIds: ['builtin_1', custom.id], customShots: [custom], droppedIds: [],
  });
});

test('apply drops catalog ids that are no longer resolvable but restores custom definitions', () => {
  const preset = { selectedIds: ['kept', 'removed', custom.id], customShots: [custom] };
  assert.deepEqual(applyShotPreset(preset, [], new Set(['kept'])), {
    selectedIds: ['kept', custom.id], customShots: [custom], droppedIds: ['removed'],
  });
});

test('rename validates duplicates and delete removes only the requested preset', () => {
  let presets = saveShotPreset([], 'One', ['a'], []);
  presets = saveShotPreset(presets, 'Two', ['b'], []);
  assert.throws(() => renameShotPreset(presets, presets[0].id, 'two'), /already exists/i);
  const renamed = renameShotPreset(presets, presets[0].id, 'First');
  assert.equal(renamed[0].name, 'First');
  assert.deepEqual(deleteShotPreset(renamed, renamed[0].id).map((item) => item.name), ['Two']);
});
