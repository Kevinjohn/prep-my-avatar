import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const hook = readFileSync(new URL('./useDataset.js', import.meta.url), 'utf8');
const workspace = readFileSync(
  new URL('../components/dataset/DatasetWorkspace.jsx', import.meta.url), 'utf8',
);

test('failed full hydration pauses automatic retries and exposes an explicit retry', () => {
  assert.match(hook, /setImageHydrationError\(/);
  assert.match(hook, /automatic hydration pauses until explicit retry/);
  assert.match(workspace, /!imageHydrationError/);
  assert.match(workspace, /onClick=\{loadAllImages\}/);
  assert.match(workspace, /reviewNeedsHydration/);
  assert.match(workspace, /Review actions stay paused until all images are loaded/);
});

test('full hydration has a request lifecycle independent from routine refreshes', () => {
  assert.match(hook, /const imageRequestSequenceRef = useRef\(0\)/);
  assert.match(hook, /const requestSequence = \+\+imageRequestSequenceRef\.current/);
  assert.doesNotMatch(
    hook.slice(hook.indexOf('const loadAllImages'), hook.indexOf('const create =')),
    /\+\+dataRequestSequenceRef\.current/,
  );
});

test('a definitive missing dataset is exposed to canonical route handling', () => {
  assert.match(hook, /const \[notFoundId, setNotFoundId\] = useState\(null\)/);
  assert.match(hook, /error\?\.status === 404[\s\S]*setNotFoundId\(dsId\)/);
  assert.match(hook, /return \{ datasets, currentId, notFoundId, data/);
});
