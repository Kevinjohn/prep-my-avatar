import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';

import { usePersistedPreference } from './usePersistedPreference.js';

test('persisted preferences read once, write changes, and contain denied storage', () => {
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const values = new Map([['choice', 'stored']]);
  let reads = 0;
  let current;
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem(key) { reads += 1; return values.get(key) ?? null; },
      setItem(key, value) { values.set(key, value); },
    },
  });
  const Harness = () => {
    current = usePersistedPreference('choice', 'fallback');
    return React.createElement('output', null, current.value);
  };
  let renderer;
  act(() => { renderer = TestRenderer.create(React.createElement(Harness)); });
  assert.equal(current.value, 'stored');
  assert.equal(reads, 1);
  act(() => { current.setValue('changed'); });
  assert.equal(values.get('choice'), 'changed');
  assert.equal(reads, 1);
  renderer.unmount();

  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem() { throw new Error('denied'); },
      setItem() { throw new Error('denied'); },
    },
  });
  const Denied = () => {
    current = usePersistedPreference('choice', 'fallback');
    return React.createElement('output', null, current.value);
  };
  act(() => { renderer = TestRenderer.create(React.createElement(Denied)); });
  assert.equal(current.value, 'fallback');
  renderer.unmount();

  if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage);
  else delete globalThis.localStorage;
});
