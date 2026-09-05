import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';
import { useTrainingMonitoring } from './useTrainingMonitoring.js';

for (const [name, flags, expected] of [
  ['another provider remains configured', { cloudConfigured: true, cloudTraining: false }, 1],
  ['legacy capabilities allow cloud training', { cloudTraining: true }, 1],
  ['no provider is configured', { cloudConfigured: false, cloudTraining: false }, 0],
  ['explicit configuration overrides the legacy flag', { cloudConfigured: false, cloudTraining: true }, 0],
]) {
  test(`cloud monitoring: ${name}`, async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const requests = [];
    t.mock.method(globalThis, 'fetch', async (url) => {
      requests.push(url);
      return new Response(JSON.stringify({ configured: true, actives: [{ run_id: 7 }] }), {
        headers: { 'Content-Type': 'application/json' },
      });
    });
    let current;
    function Harness(props) {
      current = useTrainingMonitoring({ trainingVisible: false, onNavigationStateChange: undefined, ...props });
      return null;
    }
    let renderer;
    act(() => { renderer = TestRenderer.create(React.createElement(Harness, flags)); });
    t.after(() => act(() => renderer.unmount()));
    await act(async () => { t.mock.timers.tick(1); });
    assert.equal(requests.length, expected);
    if (expected) {
      assert.equal(current.cloudStatus.actives[0].run_id, 7);
      await act(async () => { t.mock.timers.tick(5000); });
      assert.equal(requests.length, 2, 'polling continues');
      act(() => renderer.update(React.createElement(Harness, { cloudConfigured: false, cloudTraining: false })));
      await act(async () => { t.mock.timers.tick(5000); });
      assert.equal(requests.length, 2, 'polling stops when all keys are removed');
    }
    assert.ok(requests.every((url) => url === '/api/dataset/train/cloud/status'));
  });
}
