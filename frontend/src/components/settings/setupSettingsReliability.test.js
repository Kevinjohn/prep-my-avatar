import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (relative) => readFileSync(new URL(relative, import.meta.url), 'utf8');

test('subscription polling is serialized, abortable, backed off, and reports one local status', () => {
  const source = read('./EnginesSection.jsx');
  assert.doesNotMatch(source, /setInterval/);
  assert.match(source, /new AbortController\(\)/);
  assert.match(source, /Math\.min\(3000 \* \(2 \*\* failures\), 30000\)/);
  assert.match(source, /Temporarily unable to check login status\. Retrying/);
  assert.match(source, /error && <p role="alert"/);
});

test('async connection results expose status and alert live regions', () => {
  const source = read('./primitives.jsx');
  assert.match(source, /role=\{result\.ok \? 'status' : 'alert'\}/);
});

test('installer reattaches to terminal state and keeps reconnecting after poll failures', () => {
  const source = read('../setup/InstallRunner.jsx');
  assert.match(source, /handleStatus\(s\)/);
  assert.match(source, /onDone\?\.\(\)/);
  assert.match(source, /setState\('disconnected'\)/);
  assert.match(source, /Math\.min\(POLL_MS \* \(2 \*\* \(fails\.current - 1\)\), MAX_RETRY_MS\)/);
  assert.match(source, /launchDisabled = running \|\| disconnected/);
  assert.doesNotMatch(source, /launchDisabled = .*state === 'success'/);
  assert.match(source, /The install may still be running; reconnecting automatically/);
  assert.doesNotMatch(source, /MAX_POLL_FAILURES/);
});

test('guide section links preserve their routed page, move focus, and honor reduced motion', () => {
  const source = read('../../pages/GuidePage.jsx');
  assert.match(source, /href=\{`#\$\{guideHeadingRoute\(chapter\.id, item\.id\)\}`\}/);
  assert.match(source, /if \(`\$\{location\.pathname\}\$\{location\.search\}` === route\)/);
  assert.match(source, /focusGuideHeading\(id\)/);
  assert.match(source, /navigate\(route, \{ replace: true \}\)/);
  assert.match(source, /chapterId === 'getting-help' \? '\/help'/);
  assert.doesNotMatch(source, /window\.history\.pushState/);
  assert.match(source, /target\.focus\(\{ preventScroll: true \}\)/);
  assert.match(source, /prefers-reduced-motion: reduce/);
  assert.match(source, /behavior: reducedMotion \? 'auto' : 'smooth'/);
  assert.doesNotMatch(source, /<div tabIndex=\{0\} className="flex gap-2 overflow-x-auto/);
});

test('setup scan failures remain distinct from completed scans and offer retry', () => {
  const source = read('../../pages/SetupPage.jsx');
  const workflow = read('../../hooks/useSetupSettings.js');
  assert.match(workflow, /setScanError\(error\.message \|\| 'The machine scan could not be completed\.'\)/);
  assert.match(source, /scanError && !detecting/);
  assert.match(source, /role="alert"/);
  assert.match(source, /Retry scan/);
  assert.match(source, /scanned && !detecting && !scanError/);
});
