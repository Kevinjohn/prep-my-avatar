import test from 'node:test';
import assert from 'node:assert/strict';
import { datasetIdentityComplete } from './datasetIdentityRules.js';

const character = { name: 'Ada', trigger: 'zada', description: '', isConcept: false, isStyle: false };

test('a name is always required', () => {
  assert.equal(datasetIdentityComplete({ ...character, name: '   ' }), false);
  assert.equal(datasetIdentityComplete(character), true);
});

test('character and concept need a trigger word, style does not', () => {
  assert.equal(datasetIdentityComplete({ ...character, trigger: '' }), false);
  assert.equal(datasetIdentityComplete({
    ...character, trigger: '', description: 'a lens flare', isConcept: true,
  }), false);
  // Style: the server generates the placeholder trigger, so an empty field is fine.
  assert.equal(datasetIdentityComplete({ ...character, trigger: '', isStyle: true }), true);
});

test('a concept also needs its description', () => {
  const concept = { ...character, isConcept: true };
  assert.equal(datasetIdentityComplete({ ...concept, description: ' ' }), false);
  assert.equal(datasetIdentityComplete({ ...concept, description: 'a lens flare' }), true);
});

test('the answer is a boolean, not the last truthy field', () => {
  assert.strictEqual(datasetIdentityComplete(character), true);
  assert.strictEqual(datasetIdentityComplete({ ...character, name: '' }), false);
});
