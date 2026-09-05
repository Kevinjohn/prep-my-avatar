import test from 'node:test';
import assert from 'node:assert/strict';
import { matchesQuery, sectionStatus, SETTINGS_SECTIONS } from './registry.js';

test('small-image Klein rescue terms find Scraping & sources', () => {
  const scraping = SETTINGS_SECTIONS.find((section) => section.id === 'scraping');
  for (const query of ['klein', 'small image', 'rescue', 'upscale']) {
    assert.equal(matchesQuery(scraping, query), true, query);
  }
});

test('training is ready when either supported training lane is usable', () => {
  assert.equal(sectionStatus('training', { training_visible: true, cloud_training: false, aitoolkit: { valid: true } }), 'ready');
  assert.equal(sectionStatus('training', { training_visible: true, cloud_training: true }), 'ready');
  assert.equal(sectionStatus('training', { training_visible: false, cloud_training: false }), 'off');
});

test('representative visible controls are indexed for every settings section', () => {
  const examples = {
    overview: 'next steps',
    engines: 'remote generation',
    scraping: 'source credentials',
    'local-tools': 'python interpreter',
    captioning: 'watermark',
    training: 'concurrent runs',
    server: 'access token',
    maintenance: 'integrity',
  };

  for (const section of SETTINGS_SECTIONS) {
    assert.equal(matchesQuery(section, examples[section.id]), true, section.id);
  }
});

test('both cloud providers and the provider selector find Training', () => {
  const training = SETTINGS_SECTIONS.find((section) => section.id === 'training');
  for (const query of ['vast', 'RunPod', 'cloud provider']) {
    assert.equal(matchesQuery(training, query), true, query);
  }
});
