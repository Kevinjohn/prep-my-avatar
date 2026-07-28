import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import TestRenderer, { act } from 'react-test-renderer'
import { createLogger, createServer } from 'vite'
import react from '@vitejs/plugin-react'

const logger = createLogger()
const logError = logger.error
logger.error = (message, options) => {
  // Middleware-mode SSR transforms do not need HMR. Some restricted runners
  // still let Vite attempt its websocket listener even with hmr:false.
  if (!String(message).startsWith('WebSocket server error:')) logError(message, options)
}
const server = await createServer({
  configFile: false,
  customLogger: logger,
  plugins: [react()],
  server: { middlewareMode: true, hmr: false },
  appType: 'custom',
})

test.after(async () => server.close())

const textOf = (node) => {
  if (node == null) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  return (node.children || []).map(textOf).join(' ')
}

test('caption tools render guidance from the dataset kind prop', async () => {
  const { default: CaptionToolsBar } = await server.ssrLoadModule(
    '/src/components/dataset/CaptionToolsBar.jsx')
  const common = {
    images: [{ id: 1, status: 'keep', caption: 'red dress in a studio' }],
    mode: 'prose',
    open: true,
  }

  let renderer
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(CaptionToolsBar, {
      ...common, kind: 'style',
    }))
  })
  const styleText = textOf(renderer.toJSON())
  assert.match(styleText, /style LoRA/i)
  assert.match(styleText, /aesthetic/i)

  await act(async () => {
    renderer.update(React.createElement(CaptionToolsBar, { ...common, kind: 'character' }))
  })
  const characterText = textOf(renderer.toJSON())
  assert.match(characterText, /identity|character/i)
  assert.notEqual(characterText, styleText)
  renderer.unmount()
})

test('Setup settings preserve edits made while an older save is in flight', async () => {
  globalThis.window = globalThis.window || {}
  globalThis.window.location = globalThis.window.location || { hash: '#/setup' }
  globalThis.window.addEventListener = globalThis.window.addEventListener || (() => {})
  globalThis.window.removeEventListener = globalThis.window.removeEventListener || (() => {})
  globalThis.document = globalThis.document || { cookie: '', querySelector: () => null }
  globalThis.HTMLMetaElement = globalThis.HTMLMetaElement || class HTMLMetaElement {}
  const { useSetupSettings } = await server.ssrLoadModule('/src/hooks/useSetupSettings.js')
  const initial = { server: { host: '127.0.0.1', port: 5000 }, ollama: {}, comfyui: {} }
  let resolveSave
  let current
  globalThis.fetch = async (url, options = {}) => {
    const value = String(url)
    if (value.endsWith('/api/settings') && !options.method) {
      return new Response(JSON.stringify({ config: initial, secrets: {} }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    if (value.endsWith('/api/setup/autodetect')) {
      return new Response(JSON.stringify({ ollama: {}, comfyui: {} }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    if (value.endsWith('/api/settings') && options.method === 'PUT') {
      return new Promise((resolve) => { resolveSave = resolve })
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  const setupDependencies = {
    refresh: async () => ({}),
    toast: { error() {}, success() {} },
  }
  const Harness = () => {
    current = useSetupSettings(setupDependencies)
    return React.createElement('output', null, current.config?.server?.port || 'loading')
  }
  let renderer
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness))
    await new Promise((resolve) => setImmediate(resolve))
  })
  assert.equal(current.config.server.port, 5000)
  await act(async () => { current.setField('server', 'port', 6000) })
  const saving = current.persist()
  await act(async () => { await Promise.resolve() })
  await act(async () => { current.setField('server', 'port', 7000) })
  await act(async () => {
    resolveSave(new Response(JSON.stringify({
      config: { ...initial, server: { ...initial.server, port: 6000 } }, secrets: {},
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    await saving
  })
  assert.equal(current.config.server.port, 7000,
    'the save response must not overwrite a newer local edit')
  renderer.unmount()
})

test('Setup autodetect persists only detected fields and preserves an intervening draft', async () => {
  globalThis.window = globalThis.window || {}
  globalThis.window.location = globalThis.window.location || { hash: '#/setup' }
  globalThis.window.addEventListener = globalThis.window.addEventListener || (() => {})
  globalThis.window.removeEventListener = globalThis.window.removeEventListener || (() => {})
  globalThis.document = globalThis.document || { cookie: '', querySelector: () => null }
  globalThis.HTMLMetaElement = globalThis.HTMLMetaElement || class HTMLMetaElement {}
  const { useSetupSettings } = await server.ssrLoadModule('/src/hooks/useSetupSettings.js')
  const initial = { server: { host: '127.0.0.1', port: 5000 }, ollama: { url: '' }, comfyui: {} }
  let resolveDetection
  let submitted
  globalThis.fetch = async (url, options = {}) => {
    const value = String(url)
    if (value.endsWith('/api/settings') && !options.method) {
      return new Response(JSON.stringify({ config: initial, secrets: {} }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    if (value.endsWith('/api/setup/autodetect')) {
      return new Promise((resolve) => { resolveDetection = resolve })
    }
    if (value.endsWith('/api/settings') && options.method === 'PUT') {
      submitted = JSON.parse(options.body)
      return new Response(JSON.stringify({
        config: { ...initial, ollama: { url: 'http://127.0.0.1:11434' } }, secrets: {},
      }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  const dependencies = { refresh: async () => ({}), toast: { error() {}, success() {} } }
  let current
  const Harness = () => {
    current = useSetupSettings(dependencies)
    return React.createElement('output', null, current.config?.server?.port || 'loading')
  }
  let renderer
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness))
    await new Promise((resolve) => setImmediate(resolve))
  })
  await act(async () => { current.setField('server', 'port', 7000) })
  await act(async () => {
    resolveDetection(new Response(JSON.stringify({
      ollama: { url: 'http://127.0.0.1:11434' }, comfyui: {},
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    await new Promise((resolve) => setImmediate(resolve))
  })
  assert.deepEqual(submitted.config, { ollama: { url: 'http://127.0.0.1:11434' } },
    'autodetect PUT must not include the edited server draft')
  assert.equal(current.config.server.port, 7000)
  assert.equal(current.config.ollama.url, 'http://127.0.0.1:11434')
  renderer.unmount()
})

test('Studio hook retries initial failure, rejects stale refresh, and recovers after resume', async () => {
  globalThis.window = globalThis.window || {}
  globalThis.document = globalThis.document || {
    cookie: '',
    querySelector: () => null,
  }
  globalThis.HTMLMetaElement = globalThis.HTMLMetaElement || class HTMLMetaElement {}
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { useStudioRun } = await server.ssrLoadModule('/src/hooks/useStudioRun.js')
  let current
  const Harness = () => {
    current = useStudioRun('run-1', { pollMs: 10 })
    return React.createElement('output', null, current.data?.marker || current.error || 'empty')
  }

  const status = (marker, pending = 0, resumable = 0) => new Response(JSON.stringify({
    marker, pending, resumable,
  }), { status: 200, headers: { 'content-type': 'application/json' } })
  let statusCalls = 0
  globalThis.fetch = async (url, options = {}) => {
    if (String(url).includes('/status')) {
      statusCalls += 1
      if (statusCalls === 1) return new Response(JSON.stringify({ error: 'temporary' }), {
        status: 503, headers: { 'content-type': 'application/json' },
      })
      return status(`poll-${statusCalls}`, 0, 1)
    }
    if (String(url).includes('/resume') && options.method === 'POST') {
      return new Response(JSON.stringify({ ok: true, resumed: 1 }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  let renderer
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(
      ToastProvider, null, React.createElement(Harness)))
    await new Promise((resolve) => setTimeout(resolve, 30))
  })
  assert.ok(statusCalls >= 2, 'the failed first request should be retried by polling')
  assert.match(current.data.marker, /^poll-/)

  const deferred = []
  globalThis.fetch = (url, options = {}) => {
    if (String(url).includes('/status')) {
      return new Promise((resolve) => deferred.push(resolve))
    }
    if (String(url).includes('/resume') && options.method === 'POST') {
      return Promise.resolve(new Response(JSON.stringify({ ok: true, resumed: 1 }), {
        status: 200, headers: { 'content-type': 'application/json' },
      }))
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  let first
  let second
  await act(async () => {
    first = current.refresh()
    second = current.refresh()
  })
  await act(async () => {
    deferred[1](status('newest'))
    await second
    deferred[0](status('stale'))
    await first
  })
  assert.equal(current.data.marker, 'newest')

  let resumed
  resumed = current.resume()
  while (deferred.length < 3) await new Promise((resolve) => setImmediate(resolve))
  await act(async () => {
    deferred[2](status('recovered', 0, 0))
    await resumed
  })
  assert.equal(current.data.marker, 'recovered')

  globalThis.fetch = async (url) => {
    if (String(url).includes('/rate')) {
      return new Response(JSON.stringify({ ok: false, error: 'vote rejected' }), {
        status: 409, headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  let voteResult
  await act(async () => { voteResult = await current.rate('image-1', 1) })
  assert.equal(voteResult, false)
  assert.equal(current.data.marker, 'recovered', 'a failed vote must not invent refreshed state')
  renderer.unmount()
})

test('LoRA Studio keeps polling bounded and loads older runs only through pagination', async () => {
  globalThis.window = globalThis.window || {}
  globalThis.document = globalThis.document || { cookie: '', querySelector: () => null }
  globalThis.HTMLMetaElement = globalThis.HTMLMetaElement || class HTMLMetaElement {}
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { useLoraTestStudio } = await server.ssrLoadModule('/src/hooks/useLoraTestStudio.js')
  const calls = []
  globalThis.fetch = async (url) => {
    calls.push(String(url))
    if (String(url).includes('/lora-test/runs')) {
      const older = String(url).includes('cursor=19')
      return new Response(JSON.stringify(older
        ? { runs: [{ run_id: 'run-old', cells: 2 }], next_cursor: null }
        : { runs: [{ run_id: 'run-new', cells: 1 }], next_cursor: 19 }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    if (String(url).includes('/lora-test/status')) {
      const selected = new URL(String(url), 'http://local').searchParams.get('run_id') || 'run-new'
      return new Response(JSON.stringify({
        selected_run_id: selected, pending: 0, cells: [{ id: selected, run_id: selected }],
      }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  let current
  const Harness = () => {
    current = useLoraTestStudio(7, 'zimage')
    return React.createElement('output', null, current.data?.selected_run_id || 'empty')
  }
  let renderer
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(
      ToastProvider, null, React.createElement(Harness)))
    await new Promise((resolve) => setTimeout(resolve, 10))
  })
  assert.equal(current.runHistory[0].run_id, 'run-new')
  assert.equal(calls.filter((url) => url.includes('/lora-test/runs')).length, 1)
  await act(async () => { await current.loadRunHistory({ append: true }) })
  assert.deepEqual(current.runHistory.map((run) => run.run_id), ['run-new', 'run-old'])
  await act(async () => { await current.selectRun('run-old') })
  assert.equal(current.data.selected_run_id, 'run-old')
  assert.ok(calls.some((url) => url.includes('/status?') && url.includes('run_id=run-old')))
  renderer.unmount()
})

test('dataset hook rejects switched and stale payloads, paginates, hydrates, and invalidates on unmount', async () => {
  globalThis.window = globalThis.window || {}
  globalThis.window.addEventListener = () => {}
  globalThis.window.removeEventListener = () => {}
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  globalThis.EventSource = class {
    addEventListener() {}
    close() { this.closed = true }
  }
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { useDataset } = await server.ssrLoadModule('/src/hooks/useDataset.js')
  let resolveOldMeta
  let resolveOldImages
  let resolveHydration
  let dataset4Refreshes = 0
  let dataset5Hydrations = 0
  let current
  const json = (payload) => new Response(JSON.stringify(payload), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
  globalThis.fetch = (url) => {
    const value = String(url)
    if (value.endsWith('/api/dataset/list')) return Promise.resolve(json({ datasets: [] }))
    if (value.includes('/api/dataset/1?')) return new Promise((resolve) => { resolveOldMeta = resolve })
    if (value.includes('/api/dataset/1/images')) return new Promise((resolve) => { resolveOldImages = resolve })
    if (value.includes('/api/dataset/2?')) return Promise.resolve(json({ id: 2, name: 'new' }))
    if (value.includes('/api/dataset/2/images') && value.includes('cursor=next')) {
      return Promise.resolve(json({ images: [{ id: 101, caption: 'page two' }], page: { has_more: false } }))
    }
    if (value.includes('/api/dataset/2/images')) {
      return Promise.resolve(json({
        images: Array.from({ length: 100 }, (_, index) => ({ id: index + 1, caption: 'fresh' })),
        page: { has_more: true, next_cursor: 'next' },
      }))
    }
    if (value.includes('/api/dataset/3?')) return Promise.resolve(json({ id: 3, name: 'hydrate' }))
    if (value.includes('/api/dataset/3/images') && value.includes('cursor=h1')) {
      return Promise.resolve(json({ images: [{ id: 101 }], page: { has_more: true, next_cursor: 'h2' } }))
    }
    if (value.includes('/api/dataset/3/images') && value.includes('cursor=h2')) {
      return Promise.resolve(json({ images: [{ id: 102 }], page: { has_more: false } }))
    }
    if (value.includes('/api/dataset/3/images')) {
      return Promise.resolve(json({
        images: Array.from({ length: 100 }, (_, index) => ({ id: index + 1 })),
        page: { has_more: true, next_cursor: 'h1' },
      }))
    }
    if (value.includes('/api/dataset/4?')) {
      dataset4Refreshes += 1
      return Promise.resolve(json({ id: 4, name: 'freshness' }))
    }
    if (value.includes('/api/dataset/4/images') && value.includes('cursor=f1')) {
      return new Promise((resolve) => { resolveHydration = resolve })
    }
    if (value.includes('/api/dataset/4/images')) return Promise.resolve(json({
      images: Array.from({ length: 100 }, (_, index) => ({
        id: index + 1, caption: index === 0 && dataset4Refreshes > 1 ? 'newer' : 'initial',
      })), page: { has_more: true, next_cursor: 'f1' },
    }))
    if (value.includes('/api/dataset/5?')) return Promise.resolve(json({ id: 5, name: 'retry' }))
    if (value.includes('/api/dataset/5/images') && value.includes('cursor=retry')) {
      dataset5Hydrations += 1
      if (dataset5Hydrations === 1) return Promise.reject(new Error('page unavailable'))
      return Promise.resolve(json({ images: [{ id: 101 }], page: { has_more: false } }))
    }
    if (value.includes('/api/dataset/5/images')) return Promise.resolve(json({
      images: Array.from({ length: 100 }, (_, index) => ({ id: index + 1 })),
      page: { has_more: true, next_cursor: 'retry' },
    }))
    throw new Error(`Unexpected request: ${url}`)
  }
  const Harness = () => {
    current = useDataset()
    return React.createElement('output', null, current.data?.name || 'none')
  }
  let renderer
  await act(async () => { renderer = TestRenderer.create(React.createElement(ToastProvider, null, React.createElement(Harness))) })
  let oldOpen
  await act(async () => { oldOpen = current.open(1) })
  await act(async () => { await current.open(2) })
  assert.equal(current.data.id, 2)
  await act(async () => {
    resolveOldMeta(json({ id: 1, name: 'stale' }))
    resolveOldImages(json({ images: [{ id: 99 }], page: { has_more: false } }))
    await oldOpen
  })
  assert.equal(current.data.id, 2, 'late dataset switch must not publish')
  await act(async () => { await current.loadMoreImages() })
  assert.equal(current.data.images.length, 101)
  assert.equal(current.data.images.at(-1).id, 101)
  await act(async () => { await current.open(3) })
  await act(async () => { await current.loadAllImages() })
  assert.equal(current.data.images.length, 102)
  assert.equal(current.hasMoreImages, false)
  await act(async () => { await current.open(4) })
  let hydration
  await act(async () => { hydration = current.loadAllImages() })
  await act(async () => { await current.refresh() })
  await act(async () => {
    resolveHydration(json({ images: [{ id: 1, caption: 'stale' }, { id: 101 }], page: { has_more: false } }))
    await hydration
  })
  assert.equal(current.data.images.find((image) => image.id === 1).caption, 'newer')
  await act(async () => { await current.open(5) })
  await act(async () => { await current.loadAllImages() })
  assert.match(current.imageHydrationError, /Network error/)
  assert.equal(current.loadingMoreImages, false)
  await act(async () => { await current.loadAllImages() })
  assert.equal(current.imageHydrationError, null)
  assert.equal(current.hasMoreImages, false)
  renderer.unmount()
  assert.equal(current.currentId, 5, 'the last rendered snapshot remains inspectable')
})

test('capabilities context publishes newest compatibility envelope and invalidates unmounted requests', async () => {
  globalThis.document = globalThis.document || { cookie: '', querySelector: () => null }
  globalThis.HTMLMetaElement = globalThis.HTMLMetaElement || class HTMLMetaElement {}
  const { CapabilitiesProvider, useCapabilities } = await server.ssrLoadModule(
    '/src/context/CapabilitiesContext.jsx')
  const deferred = []
  globalThis.fetch = () => new Promise((resolve) => deferred.push(resolve))
  let current
  const Harness = () => {
    current = useCapabilities()
    return React.createElement('output', null, current.caps.marker || 'empty')
  }
  let renderer
  await act(async () => { renderer = TestRenderer.create(React.createElement(CapabilitiesProvider, null, React.createElement(Harness))) })
  let newer
  await act(async () => { newer = current.refresh(true) })
  const response = (marker) => new Response(JSON.stringify({
    marker, configured: true, engines: {}, generation_pricing: { per_image: {} },
  }), { status: 200, headers: { 'content-type': 'application/json' } })
  await act(async () => {
    deferred[1](response('new'))
    await newer
    deferred[0](response('old'))
    await new Promise((resolve) => setImmediate(resolve))
  })
  assert.equal(current.caps.marker, 'new')
  let pending
  await act(async () => { pending = current.refresh() })
  renderer.unmount()
  deferred[2](response('after-unmount'))
  await pending
  assert.equal(current.caps.marker, 'new')
})

test('variation engine workflow reconciles persisted availability from settings and capabilities', async () => {
  const { useVariationEngines } = await server.ssrLoadModule('/src/hooks/useVariationEngines.js')
  globalThis.localStorage = {
    value: 'nanobanana', getItem() { return this.value }, setItem(_key, value) { this.value = value },
  }
  globalThis.document = globalThis.document || { cookie: '', querySelector: () => null }
  globalThis.HTMLMetaElement = globalThis.HTMLMetaElement || class HTMLMetaElement {}
  globalThis.fetch = async () => new Response(JSON.stringify({
    config: { engines: { enabled: ['klein'], chatgpt_auth: 'auto' }, privacy: { allow_remote_generation: false } },
  }), { status: 200, headers: { 'content-type': 'application/json' } })
  let current
  const Harness = () => {
    current = useVariationEngines({
      engines: { nanobanana: true, chatgpt: true, klein: true },
      comfyui: { reachable: true }, chatgpt_subscription: { connected: false },
    })
    return React.createElement('output', null, current.generator)
  }
  let renderer
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness))
    await new Promise((resolve) => setImmediate(resolve))
  })
  assert.equal(current.generator, 'klein')
  assert.equal(current.currentAvailable, true)
  assert.equal(globalThis.localStorage.value, 'klein')
  renderer.unmount()
})
