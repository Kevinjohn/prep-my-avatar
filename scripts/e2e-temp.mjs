import { existsSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { constants } from 'node:os';

export const E2E_PREFIX = 'prep-my-avatar-e2e-';
const MARKER = '.prep-my-avatar-e2e-owned';
const DEFAULT_MAX_AGE_MS = 24 * 60 * 60 * 1000;

export function markOwned(directory, now = Date.now()) {
  writeFileSync(join(directory, MARKER), `${now}\n`, { flag: 'wx' });
}

export function removeOwned(directory) {
  if (!existsSync(join(directory, MARKER))) return false;
  rmSync(directory, { recursive: true, force: true });
  return true;
}

export function childExitCode(code, signal) {
  if (signal) return 128 + (constants.signals[signal] || 0);
  return code ?? 1;
}

export function scavengeStaleOwned(parent, now = Date.now(), maxAgeMs = DEFAULT_MAX_AGE_MS) {
  for (const entry of readdirSync(parent, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.startsWith(E2E_PREFIX)) continue;
    const directory = join(parent, entry.name);
    const marker = join(directory, MARKER);
    try {
      const createdAt = Number.parseInt(readFileSync(marker, 'utf8').trim(), 10);
      const fallbackTime = statSync(marker).mtimeMs;
      if (now - (Number.isFinite(createdAt) ? createdAt : fallbackTime) >= maxAgeMs) {
        removeOwned(directory);
      }
    } catch {
      // Never delete an unmarked or unreadable directory merely because its name matches.
    }
  }
}
