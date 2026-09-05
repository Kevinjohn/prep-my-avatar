import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const source = readFileSync(new URL('./TrainingSection.jsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
});
const exports = {};
runInNewContext(outputText, {
  exports,
  require: (id) => {
    if (id === './primitives') return {
      INPUT_CLASS: '',
      Card: ({ title, children }) => React.createElement('section', { title }, children),
      SecretField: ({ field }) => React.createElement('secret-field', { field }),
    };
    if (id === '../../api/fetchClient') return { safeJson: async () => ({ month_spend: 0 }) };
    return require(id);
  },
});

test('provider selection keeps both keys and switches provider-specific controls without losing nested settings', async () => {
  const updates = [];
  const config = {
    training: { default_family: 'flux' },
    cloud: { provider: 'vast', min_reliability: 0.97,
      runpod: { image: 'custom/image', template_id: 'template', ui_port: 8675, cloud_type: 'SECURE' } },
  };
  const props = { config, setField: (...args) => updates.push(args) };
  let renderer;
  await act(async () => { renderer = TestRenderer.create(React.createElement(exports.default, props)); });
  try {
    assert.equal(renderer.root.findByProps({ id: 'cloud-provider' }).props.value, 'vast');
    assert.equal(renderer.root.findByProps({ id: 'cloud-min-reliability' }).props.value, 0.97);
    const secrets = renderer.root.findAllByType('secret-field').map((node) => node.props.field);
    assert.deepEqual(secrets.map(({ key, testTarget }) => [key, testTarget]), [
      ['VAST_API_KEY', 'vast'], ['RUNPOD_API_KEY', 'runpod'],
    ]);
    renderer.root.findByProps({ id: 'cloud-provider' }).props.onChange({ target: { value: 'runpod' } });
    assert.deepEqual(updates.pop(), ['cloud', 'provider', 'runpod']);
    await act(async () => renderer.update(React.createElement(exports.default, {
      ...props, config: { ...config, cloud: { ...config.cloud, provider: 'runpod' } },
    })));
    assert.equal(renderer.root.findAllByProps({ id: 'cloud-min-reliability' }).length, 0);
    const cloudType = renderer.root.findByProps({ id: 'cloud-runpod-cloud-type' });
    assert.equal(cloudType.props.value, 'SECURE');
    cloudType.props.onChange({ target: { value: 'COMMUNITY' } });
    const [section, key, value] = updates.pop();
    assert.equal(section, 'cloud');
    assert.equal(key, 'runpod');
    assert.deepEqual({ ...value }, { ...config.cloud.runpod, cloud_type: 'COMMUNITY' });
  } finally {
    act(() => renderer.unmount());
  }
});
