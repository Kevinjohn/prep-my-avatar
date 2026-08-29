import test from 'node:test';
import assert from 'node:assert/strict';
import {
  captionIsAsserted,
  captionOriginInfo,
  captionOriginTooltipLine,
  captionRewriteCounts,
} from './captionOrigin.js';

test('known caption origins have stable honest labels', () => {
  assert.deepEqual(
    ['asserted', 'joycaption', 'ollama'].map((origin) => captionOriginInfo(origin).short),
    ['You wrote this', 'Written by JoyCaption', 'Written by the local vision model'],
  );
  assert.equal(captionIsAsserted('asserted'), true);
  assert.equal(captionIsAsserted('joycaption'), false);
});

test('unrecorded authorship remains unknown rather than becoming machine attribution', () => {
  for (const origin of [null, undefined, '', '   ']) {
    const info = captionOriginInfo(origin);
    assert.equal(info.short, 'Author not recorded');
    assert.equal(info.known, false);
    assert.doesNotMatch(`${info.chip} ${info.short} ${info.title}`, /machine-generated/i);
  }
});

test('future origins stay visible under their stored name', () => {
  const info = captionOriginInfo(' Future-Engine ');
  assert.equal(info.key, 'future-engine');
  assert.equal(info.chip, 'future-engine');
  assert.equal(info.short, 'Written by future-engine');
  assert.equal(info.known, true);
  assert.match(info.title, /does not know/i);
});

test('empty captions display no author even if an origin is present', () => {
  assert.equal(captionOriginTooltipLine('', 'asserted'), '');
  assert.equal(captionOriginTooltipLine('   ', 'joycaption'), '');
  assert.equal(captionOriginTooltipLine('saved words', 'asserted'), 'You wrote this');
});

test('rewrite counts match protected forced-batch admission', () => {
  const counts = captionRewriteCounts([
    { status: 'keep', caption: 'human', caption_origin: 'asserted' },
    { status: 'keep', caption: 'joy', caption_origin: 'joycaption' },
    { status: 'keep', caption: 'ollama', caption_origin: 'ollama' },
    { status: 'keep', caption: 'legacy', caption_origin: null },
    { status: 'keep', caption: 'future', caption_origin: 'future-engine' },
    { status: 'keep', caption: '', caption_origin: 'asserted' },
    { status: 'reject', caption: 'not admitted', caption_origin: 'joycaption' },
  ]);

  assert.deepEqual(counts, {
    blank: 1,
    machine: 2,
    asserted: 1,
    unrecorded: 1,
    unknown: 1,
    rewrite: 5,
    spared: 1,
    rewriteWithAsserted: 6,
  });
});
