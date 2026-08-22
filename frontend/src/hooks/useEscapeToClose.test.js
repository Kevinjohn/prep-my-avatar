import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';
import { JSDOM } from 'jsdom';

import { useEscapeToClose } from './useEscapeToClose.js';

function pressKey(window, key) {
  window.dispatchEvent(new window.KeyboardEvent('keydown', { key }));
}

test('useEscapeToClose responds only to Escape while enabled', () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const dom = new JSDOM();
  globalThis.window = dom.window;
  let closeCalls = 0;
  const Harness = ({ enabled }) => {
    useEscapeToClose(() => { closeCalls += 1; }, enabled);
    return null;
  };
  let renderer;

  try {
    act(() => {
      renderer = TestRenderer.create(React.createElement(Harness, { enabled: true }));
    });
    pressKey(dom.window, 'Enter');
    assert.equal(closeCalls, 0);
    pressKey(dom.window, 'Escape');
    assert.equal(closeCalls, 1);

    act(() => {
      renderer.update(React.createElement(Harness, { enabled: false }));
    });
    pressKey(dom.window, 'Escape');
    assert.equal(closeCalls, 1);

    act(() => { renderer.unmount(); });
    pressKey(dom.window, 'Escape');
    assert.equal(closeCalls, 1);
  } finally {
    dom.window.close();
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
    else delete globalThis.window;
  }
});
