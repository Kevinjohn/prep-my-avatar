import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dataDir = mkdtempSync(join(tmpdir(), 'prep-my-avatar-e2e-'));
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
function stop(signal = 'SIGTERM') {
  if (stopping) return;
  stopping = true;
  if (!child.killed) child.kill(signal);
}
process.on('SIGTERM', () => stop('SIGTERM'));
process.on('SIGINT', () => stop('SIGINT'));
child.on('exit', (code, signal) => {
  rmSync(dataDir, { recursive: true, force: true });
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
