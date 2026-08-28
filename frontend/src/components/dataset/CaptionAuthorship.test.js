import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { captionAttributionState } from '../../utils/captionOrigin.js';

const gridItem = readFileSync(new URL('./DatasetGridItem.jsx', import.meta.url), 'utf8');
const dialog = readFileSync(new URL('./CaptionEditorDialog.jsx', import.meta.url), 'utf8');

test('saved, unsaved, and legacy caption attribution states stay distinct', () => {
  const saved = captionAttributionState('saved caption', 'joycaption', 'saved caption');
  assert.equal(saved.kind, 'saved');
  assert.equal(saved.short, 'Written by JoyCaption');

  const draft = captionAttributionState('saved caption', 'joycaption', 'edited draft');
  assert.equal(draft.kind, 'draft');
  assert.equal(draft.short, 'Unsaved edit');
  assert.match(draft.title, /save.*your caption/i);
  assert.doesNotMatch(`${draft.short} ${draft.title}`, /JoyCaption/);

  const legacy = captionAttributionState('legacy caption', null, 'legacy caption');
  assert.equal(legacy.kind, 'saved');
  assert.equal(legacy.short, 'Author not recorded');
  assert.equal(legacy.known, false);
});

test('empty saved captions have no attribution until a draft exists', () => {
  assert.equal(captionAttributionState('', 'asserted', ''), null);
  assert.equal(captionAttributionState('', 'asserted', 'new draft').kind, 'draft');
});

test('tile and expanded editor render the shared accessible attribution state', () => {
  assert.match(gridItem, /captionAttributionState\(img\.caption, img\.caption_origin, cap\)/);
  assert.match(gridItem, /aria-label=\{attribution\.short\}/);
  assert.match(gridItem, /attribution\.kind === 'draft' \|\| attribution\.known/);
  assert.match(gridItem, /savedCaption=\{img\.caption \|\| ''\}/);
  assert.match(gridItem, /captionOrigin=\{img\.caption_origin\}/);

  assert.match(dialog, /captionAttributionState\(savedCaption, captionOrigin, draft\)/);
  assert.match(dialog, /aria-live="polite"/);
  assert.match(dialog, /\{attribution\.short\}/);
  assert.match(dialog, /\{attribution\.title\}/);
});
