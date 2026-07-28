import test from 'node:test';
import assert from 'node:assert/strict';
import { CROP_MIN_SIDE, clampRatioCropBox } from './cropGeometry.js';

for (const ratio of [1, 3 / 4, 2 / 3, 9 / 16, 4 / 3, 3 / 2, 16 / 9]) {
  test(`fixed crop preserves ratio and minimum at ${ratio}`, () => {
    for (const candidate of [1, 18, 32, 47, 200, 2000]) {
      const box = clampRatioCropBox({ x: -10, y: 999, w: candidate, h: candidate / ratio }, ratio, 640, 480);
      assert.ok(Math.abs((box.w / box.h) - ratio) < 1e-9);
      assert.ok(box.w >= CROP_MIN_SIDE);
      assert.ok(box.h >= CROP_MIN_SIDE);
      assert.ok(box.x >= 0 && box.y >= 0);
      assert.ok(box.x + box.w <= 640 + 1e-9);
      assert.ok(box.y + box.h <= 480 + 1e-9);
    }
  });
}
