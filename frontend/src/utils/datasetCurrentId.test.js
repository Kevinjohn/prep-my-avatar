import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clearDatasetCurrentId, readDatasetCurrentId, writeDatasetCurrentId,
} from './datasetCurrentId.js';

function withStorage(storage, callback) {
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage });
  try {
    callback();
  } finally {
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage);
    else delete globalThis.localStorage;
  }
}

test('readDatasetCurrentId preserves the existing stored-id parsing', () => {
  const values = new Map([['datasetCurrentId', '42']]);
  withStorage({ getItem: (key) => values.get(key) ?? null }, () => {
    assert.equal(readDatasetCurrentId(), 42);
    values.set('datasetCurrentId', '0');
    assert.equal(readDatasetCurrentId(), 0);
    values.delete('datasetCurrentId');
    assert.equal(readDatasetCurrentId(), null);
  });
});

test('writeDatasetCurrentId stores the hand-off value under the shared key', () => {
  const values = new Map();
  withStorage({ setItem: (key, value) => values.set(key, value) }, () => {
    writeDatasetCurrentId(42);
    assert.equal(values.get('datasetCurrentId'), '42');
  });
});

test('clearDatasetCurrentId removes the shared key', () => {
  const values = new Map([['datasetCurrentId', '42']]);
  withStorage({ removeItem: (key) => values.delete(key) }, () => {
    clearDatasetCurrentId();
    assert.equal(values.has('datasetCurrentId'), false);
  });
});

test('dataset-current-id helpers contain private-mode storage failures', () => {
  const denied = () => { throw new DOMException('denied', 'SecurityError'); };
  withStorage({ getItem: denied, setItem: denied, removeItem: denied }, () => {
    assert.equal(readDatasetCurrentId(), null);
    assert.doesNotThrow(() => writeDatasetCurrentId(42));
    assert.doesNotThrow(() => clearDatasetCurrentId());
  });
});
