import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'

const result = spawnSync(process.execPath, [
  'node_modules/typescript/bin/tsc', '-p', 'tsconfig.check.json', '--listFilesOnly',
], { cwd: new URL('..', import.meta.url), encoding: 'utf8' })
if (result.status !== 0) throw new Error(result.stderr || result.stdout)

const files = result.stdout.replaceAll('\\', '/').split('\n')
for (const representative of [
  '/src/App.jsx',
  '/src/pages/SettingsPage.jsx',
  '/src/components/dataset/TrainingPanel.jsx',
  '/src/context/CapabilitiesContext.jsx',
  '/src/hooks/useDataset.js',
]) {
  assert.ok(files.some((file) => file.endsWith(representative)),
    `frontend typecheck omitted ${representative}`)
}
console.log('Typecheck coverage includes app, page, component, context, and hook modules.')
