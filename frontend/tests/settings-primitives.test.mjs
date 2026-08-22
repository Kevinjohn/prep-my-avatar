import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createLogger, createServer } from 'vite'
import react from '@vitejs/plugin-react'

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/', pretendToBeVisual: true,
})
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'MouseEvent']) {
  Object.defineProperty(globalThis, key, { configurable: true, value: dom.window[key] })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const logger = createLogger()
const logError = logger.error
logger.error = (message, options) => {
  if (!String(message).startsWith('WebSocket server error:')) logError(message, options)
}
const server = await createServer({
  configFile: false, customLogger: logger, plugins: [react()],
  server: { middlewareMode: true, hmr: false }, appType: 'custom',
})

test.after(async () => {
  await server.close()
  dom.window.close()
})

test('settings toggle preserves switch semantics and delegates clicks', async () => {
  const { render, fireEvent, screen, cleanup } = await import('@testing-library/react')
  const { ToggleSwitch } = await server.ssrLoadModule('/src/components/settings/primitives.jsx')
  let clicks = 0
  const mounted = render(React.createElement(ToggleSwitch, {
    checked: false,
    label: 'Remote access',
    onClick: () => { clicks += 1 },
  }))
  const toggle = screen.getByRole('switch', { name: 'Remote access' })
  assert.equal(toggle.getAttribute('aria-checked'), 'false')
  fireEvent.click(toggle)
  assert.equal(clicks, 1)

  mounted.rerender(React.createElement(ToggleSwitch, {
    checked: true,
    label: 'Remote access',
    onClick: () => { clicks += 1 },
  }))
  assert.equal(toggle.getAttribute('aria-checked'), 'true')
  cleanup()
})
