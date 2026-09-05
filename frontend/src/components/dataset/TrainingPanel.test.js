import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const { outputText } = ts.transpileModule(readFileSync(new URL('./TrainingPanel.jsx', import.meta.url), 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
});

async function renderPanel(t, caps, cloudStatus = {}) {
  const exports = {};
  const noop = () => {};
  const checkpointBrowser = {
    trainType: 'zimage', base: '', checkpoints: [], imported: [], cloudCheckpoints: [],
    setTrainType: noop, setBase: noop, refresh: noop,
  };
  const monitoringInputs = [];
  const requests = [];
  runInNewContext(outputText, {
    exports,
    require: (id) => {
      if (id === 'react-router-dom') return { Link: ({ children }) => React.createElement('a', {}, children) };
      if (id.includes('CapabilitiesContext')) return { useCapabilities: () => ({ caps }) };
      if (id.includes('fetchClient')) return { getJson: async (url) => {
        requests.push(url);
        if (url.includes('/preflight?')) return { floor: 20, blockers: [] };
        if (url.includes('/feedback?')) return {};
        throw new Error(`Unexpected request: ${url}`);
      } };
      if (id.includes('/Toast')) return { useToast: () => ({ error: noop, success: noop }) };
      if (id.includes('ConfirmDialog')) return { useConfirmDialog: () => noop, usePromptDialog: () => noop };
      if (id.includes('useTrainingMonitoring')) return { useTrainingMonitoring: (input) => {
        monitoringInputs.push(input);
        return { status: { installed: false, in_progress: false, queue: [] }, statusLoaded: true, cloudStatus, refreshStatus: noop };
      } };
      if (id === './useCheckpointBrowser') return { useCheckpointBrowser: () => checkpointBrowser };
      if (id === './useTrainingPresets') return { useTrainingPresets: () => ({}) };
      if (id.includes('useTrainingLaunch')) return { useTrainingLaunch: () => ({
        stepsOverrideValid: true, hasInvalidStepsOverride: false, stepsOverride: '',
      }) };
      if (['./TrainingProgress', './ResumeTrainingDialog', './PreflightModal', './CloudLaunchDialog',
        './TrainingAdvancedOptions', './TrainingCheckpointBrowserView'].includes(id)) return { default: () => null };
      return require(id.startsWith('.') ? `${id}.js` : id);
    },
  });
  const ds = {
    currentId: 7,
    trainBaseInfo: async () => ({ train_type: 'zimage', base: '', train_settings: {} }),
    listCheckpoints: async () => ({}),
  };
  let renderer;
  await act(async () => { renderer = TestRenderer.create(React.createElement(exports.default, { ds, keptCount: 25 })); });
  t.after(() => act(() => renderer.unmount()));
  return { renderer, monitoringInputs, requests };
}

function textContent(node) {
  return typeof node === 'string' ? node : node.children.map(textContent).join('');
}

function cloudButtons(renderer) {
  return renderer.root.findAllByType('button').filter((button) => textContent(button).includes('Train in cloud'));
}

test('hidden training explains both local and cloud provider setup options', async (t) => {
  const { renderer, monitoringInputs, requests } = await renderPanel(t, {});
  assert.equal(textContent(renderer.root.findByType('div')), '🎓Training needs ai-toolkit (local GPU) or a cloud GPU API key (vast.ai or RunPod) — set either in Settings.');
  assert.equal(cloudButtons(renderer).length, 0);
  assert.ok(monitoringInputs.every((input) => !input.trainingVisible));
  assert.ok(!requests.some((url) => url.includes('/preflight?')));
});

test('a configured RunPod key alone shows training when local tools and selected-provider launch are unavailable', async (t) => {
  const { renderer, monitoringInputs } = await renderPanel(t, {
    cloud_configured: true, cloud_training: false,
    cloud_provider: { label: 'RunPod' },
  });
  assert.match(textContent(renderer.root), /LoRA Training/);
  assert.match(textContent(renderer.root), /ai-toolkit not installed/);
  assert.ok(monitoringInputs.every((input) => input.trainingVisible === true && input.cloudConfigured === true));
  assert.equal(cloudButtons(renderer).length, 0);
});

for (const [name, flags, visible] of [
  ['configured without selected-provider launch', { cloud_configured: true, cloud_training: false }, true],
  ['explicitly unconfigured despite launch flag', { cloud_configured: false, cloud_training: true }, false],
  ['legacy launch capability', { cloud_training: true }, true],
  ['no cloud capabilities', {}, false],
]) {
  test(`last cloud checkpoint card: ${name}`, async (t) => {
    const { renderer } = await renderPanel(t, { training_visible: true, ...flags }, {
      last: { dataset_id: 7, train_type: 'zimage', status: 'done', checkpoint_ready: true },
    });
    const links = renderer.root.findAllByType('a').filter((link) => textContent(link).includes('Download the cloud-trained LoRA'));
    assert.equal(links.length, visible ? 1 : 0);
    if (visible) assert.equal(links[0].props.href, '/api/dataset/7/train/cloud/checkpoint?train_type=zimage');
  });
}

for (const [name, provider, label] of [
  ['RunPod label', { label: 'RunPod' }, 'RunPod'],
  ['missing provider', undefined, 'vast.ai'],
  ['missing label', {}, 'vast.ai'],
]) {
  test(`cloud launch button title uses ${name}`, async (t) => {
    const { renderer } = await renderPanel(t, { cloud_training: true, cloud_provider: provider });
    const buttons = cloudButtons(renderer);
    assert.equal(buttons.length, 1);
    assert.equal(buttons[0].props.title, `Rents a ${label} GPU for this run`);
    assert.equal(buttons[0].props.disabled, false);
    assert.match(textContent(buttons[0]), /☁️/);
  });
}

for (const cloudTraining of [undefined, false, true]) {
  test(`configured cloud training renders an enabled launch button only for cloud_training=true (${cloudTraining})`, async (t) => {
    const { renderer } = await renderPanel(t, { cloud_configured: true, cloud_training: cloudTraining });
    const buttons = cloudButtons(renderer);
    assert.equal(buttons.length, cloudTraining === true ? 1 : 0);
    if (cloudTraining === true) assert.equal(buttons[0].props.disabled, false);
  });
}
