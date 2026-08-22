import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';

import { useInFlightIds } from './useInFlightIds.js';

function renderHook() {
  let current;
  const Harness = () => {
    current = useInFlightIds();
    return null;
  };
  let renderer;
  act(() => { renderer = TestRenderer.create(React.createElement(Harness)); });
  return { getCurrent: () => current, renderer };
}

test('useInFlightIds ignores duplicate work and clears the id after resolution', async () => {
  const { getCurrent, renderer } = renderHook();
  let resolveWork;
  let workCalls = 0;
  const work = new Promise((resolve) => { resolveWork = resolve; });
  let firstRun;

  act(() => {
    firstRun = getCurrent().run('image-1', () => {
      workCalls += 1;
      return work;
    });
  });
  assert.equal(getCurrent().inFlight.has('image-1'), true);

  await act(async () => {
    await getCurrent().run('image-1', () => { workCalls += 1; });
  });
  assert.equal(workCalls, 1);

  await act(async () => {
    resolveWork();
    await firstRun;
  });
  assert.equal(getCurrent().inFlight.has('image-1'), false);
  renderer.unmount();
});

test('useInFlightIds clears the id after rejection and propagates the error', async () => {
  const { getCurrent, renderer } = renderHook();

  await act(async () => {
    await assert.rejects(
      getCurrent().run('image-2', async () => { throw new Error('request failed'); }),
      /request failed/,
    );
  });

  assert.equal(getCurrent().inFlight.has('image-2'), false);
  renderer.unmount();
});
