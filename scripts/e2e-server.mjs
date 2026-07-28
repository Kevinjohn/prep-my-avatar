import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { childExitCode, E2E_PREFIX, markOwned, removeOwned, scavengeStaleOwned } from './e2e-temp.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
scavengeStaleOwned(tmpdir());
const dataDir = mkdtempSync(join(tmpdir(), E2E_PREFIX));
markOwned(dataDir);
const venvPython = process.platform === 'win32'
  ? join(root, '.venv', 'Scripts', 'python.exe')
  : join(root, '.venv', 'bin', 'python');
const python = existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3');
const child = spawn(python, [join(root, 'backend', 'run.py')], {
  cwd: root,
  stdio: 'inherit',
  env: {
    ...process.env,
    LDS_DATA_DIR: dataDir,
    LDS_CONFIG: join(dataDir, 'config.json'),
    LDS_ENV: join(dataDir, '.env'),
    LDS_HOST: '127.0.0.1',
    LDS_PORT: process.env.E2E_PORT || '5075',
    LDS_NO_REEXEC: '1',
    PYTHONUNBUFFERED: '1',
  },
});

let stopping = false;
let settled = false;
function stop(signal = 'SIGTERM') {
  if (stopping) return;
  stopping = true;
  if (!child.killed) child.kill(signal);
}
process.on('SIGTERM', () => stop('SIGTERM'));
process.on('SIGINT', () => stop('SIGINT'));
child.on('error', (error) => {
  if (settled) return;
  settled = true;
  removeOwned(dataDir);
  console.error(`E2E server failed to start: ${error.message}`);
  process.exitCode = 1;
});
child.on('exit', (code, signal) => {
  if (settled) return;
  settled = true;
  removeOwned(dataDir);
  process.exitCode = childExitCode(code, signal);
});
