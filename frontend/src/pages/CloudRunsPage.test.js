import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const { outputText } = ts.transpileModule(readFileSync(new URL('./CloudRunsPage.jsx', import.meta.url), 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
});

async function renderPage(caps, data) {
  const exports = {};
  const noop = () => {};
  runInNewContext(outputText, {
    exports, URLSearchParams,
    setTimeout: () => 1, clearTimeout: noop,
    require: (id) => {
      if (id === 'react-router-dom') return { useNavigate: () => noop };
      if (id.includes('CapabilitiesContext')) return { useCapabilities: () => ({ caps }) };
      if (id.includes('fetchClient')) return { getJson: async () => data };
      if (id.includes('/Toast')) return { useToast: () => ({ info: noop, error: noop }) };
      if (id.includes('ConfirmDialog')) return { useConfirmDialog: () => noop, usePromptDialog: () => noop };
      if (id.includes('usePersistedPreference')) return { usePersistedPreference: () => ({ value: false, setValue: noop }) };
      if (id.includes('TrainingProgress') || id.includes('RunComparisonPanel')) return { default: () => null };
      if (id.includes('datasetCurrentId')) return { writeDatasetCurrentId: noop };
      if (id.includes('trainingFamilies')) return { TRAINING_FAMILY_LABELS: {} };
      return require(id);
    },
  });
  let renderer;
  await act(async () => { renderer = TestRenderer.create(React.createElement(exports.default)); });
  return renderer;
}

const runpod = { run_id: 1, source: 'cloud', provider_label: 'RunPod', console_url: 'https://console.runpod.io/pods/pod-1', vast_instance_id: 'pod-1', dataset_id: 1 };
const vast = { run_id: 2, source: 'cloud', provider_label: 'vast.ai', console_url: 'https://cloud.vast.ai/instances/', vast_instance_id: 42, dataset_id: 2 };

test('selected-provider console and mixed recovery links keep their own provider destinations', async () => {
  const renderer = await renderPage({ cloud_training: false, cloud_configured: true,
    cloud_provider: { label: 'RunPod', console_url: 'https://console.runpod.io/pods' } }, {
    configured: true, actives: [vast], recent: [runpod], recovery_required: [runpod, vast],
  });
  try {
    const links = renderer.root.findAllByType('a');
    assert.equal(links[0].props.href, 'https://console.runpod.io/pods');
    assert.ok(links[0].children.join('').includes('RunPod'));
    const recovery = renderer.root.findByType('ul').findAllByType('a');
    assert.deepEqual(recovery.map((link) => link.props.href), [runpod.console_url, vast.console_url]);
    assert.ok(recovery[0].children.join('').includes('RunPod'));
    assert.ok(recovery[1].children.join('').includes('vast.ai'));
    assert.ok(!JSON.stringify(renderer.toJSON()).includes('isn’t configured yet'));
    assert.equal(renderer.root.findAllByProps({ title: 'Cloud run (RunPod)' }).length, 1);
  } finally { act(() => renderer.unmount()); }
});

for (const [name, runs, expectedUrl, expectedLabel] of [
  ['first run', [runpod], runpod.console_url, 'RunPod'],
  ['legacy row', [{ run_id: 3, source: 'cloud' }], vast.console_url, 'vast.ai'],
  ['empty history', [], vast.console_url, 'vast.ai'],
]) {
  test(`console fallback supports ${name}`, async () => {
    const renderer = await renderPage({}, { configured: false, actives: [], recent: runs });
    try {
      const link = renderer.root.findAllByType('a')[0];
      assert.equal(link.props.href, expectedUrl);
      assert.ok(link.children.join('').includes(expectedLabel));
    } finally { act(() => renderer.unmount()); }
  });
}

for (const [name, runs, expectedLabel] of [
  ['run label', [runpod], 'RunPod'],
  ['legacy default', [{ ...vast, provider_label: undefined }], 'vast.ai'],
  ['empty history default', [], 'vast.ai'],
]) {
  test(`selected console without a label uses ${name}`, async () => {
    const renderer = await renderPage({ cloud_provider: { console_url: 'https://console.runpod.io/pods' } }, {
      configured: true, actives: runs,
    });
    try {
      const link = renderer.root.findAllByType('a')[0];
      assert.equal(link.props.href, 'https://console.runpod.io/pods');
      assert.equal(link.children.join(''), `Open the ${expectedLabel} console ↗`);
    } finally { act(() => renderer.unmount()); }
  });
}

for (const [name, data, expected] of [
  ['active before recent and recovery', { actives: [vast, runpod], recent: [runpod], recovery_required: [runpod] }, vast],
  ['first cloud history row before recovery, skipping local', { recent: [{ ...vast, run_id: 99, source: 'local' }, runpod, vast], recovery_required: [vast] }, runpod],
  ['recovery when history is local only', { recent: [{ ...vast, run_id: 99, source: 'local' }], recovery_required: [runpod, vast] }, runpod],
]) {
  test(`page console chooses ${name}`, async () => {
    const renderer = await renderPage({}, { configured: true, ...data });
    try {
      const link = renderer.root.findAllByType('a')[0];
      assert.equal(link.props.href, expected.console_url);
      assert.equal(link.children.join(''), `Open the ${expected.provider_label} console ↗`);
    } finally { act(() => renderer.unmount()); }
  });
}

for (const [name, data, showsWarning, showsStats] of [
  ['server false overrides configured capabilities', { configured: false }, true, false],
  ['missing server flag falls back to capabilities', {}, false, true],
  ['loading hides the stats despite configured capabilities', null, false, false],
]) {
  test(name, async () => {
    const renderer = await renderPage({ cloud_configured: true }, data);
    try {
      const output = JSON.stringify(renderer.toJSON());
      assert.equal(output.includes('Cloud training isn’t configured yet'), showsWarning);
      assert.equal(output.includes('/h total'), showsStats);
      assert.equal(output.includes('this month:'), showsStats);
      assert.equal(output.includes('Loading…'), data === null);
    } finally { act(() => renderer.unmount()); }
  });
}

for (const [name, provider, label, url] of [
  ['RunPod', runpod, 'RunPod', runpod.console_url],
  ['legacy', { run_id: 3, dataset_id: 3, source: 'cloud' }, 'vast.ai', vast.console_url],
]) {
  for (const instanceId of ['pod-42', undefined]) {
    test(`${name} row console title with instance ${instanceId}`, async () => {
      const renderer = await renderPage({}, {
        configured: true, actives: [{ ...provider, vast_instance_id: instanceId }],
        recent: [{ ...provider, run_id: 4 }],
      });
      try {
        const title = instanceId
          ? `${label} instance ${instanceId} — provider console (billing, logs, manual destroy)`
          : `${label} console — billing, logs, manual destroy`;
        const link = renderer.root.findByProps({ title });
        assert.equal(link.type, 'a');
        assert.equal(link.props.href, url);
        assert.equal(link.props.rel, 'noreferrer');
        assert.equal(link.children.join(''), `${label} console ↗`);
        assert.equal(renderer.root.findAllByProps({ title: `Cloud run (${label})` }).length, 1);
      } finally { act(() => renderer.unmount()); }
    });
  }
}

test('recovery entries use unique run keys even with shared or missing instance ids', async (t) => {
  const errors = [];
  t.mock.method(console, 'error', (...args) => errors.push(args.join(' ')));
  const renderer = await renderPage({}, { recovery_required: [
    { ...runpod, run_id: 11, vast_instance_id: 'shared' },
    { ...vast, run_id: 12, vast_instance_id: 'shared' },
    { run_id: 13 }, { run_id: 14 },
  ] });
  try {
    const items = renderer.root.findByType('ul').findAllByType('li');
    assert.equal(items.length, 4);
    assert.deepEqual(items.map((item) => item.findByType('a').children.join('')), [
      'RunPod console ↗ — shared', 'vast.ai console ↗ — shared',
      'vast.ai console ↗ — 13', 'vast.ai console ↗ — 14',
    ]);
    assert.deepEqual(items.map((item) => item.findByType('a').props.href), [
      runpod.console_url, vast.console_url, vast.console_url, vast.console_url,
    ]);
    assert.deepEqual(errors, [], 'React must not report missing or duplicate list keys');
  } finally { act(() => renderer.unmount()); }
});
