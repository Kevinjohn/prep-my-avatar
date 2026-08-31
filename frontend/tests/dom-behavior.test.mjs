import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createLogger, createServer } from 'vite'
import react from '@vitejs/plugin-react'

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/#/datasets', pretendToBeVisual: true,
})
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement',
  'HTMLButtonElement', 'HTMLAnchorElement', 'HTMLMetaElement', 'Element', 'Node', 'Event',
  'KeyboardEvent', 'MouseEvent', 'MutationObserver', 'getComputedStyle',
]) Object.defineProperty(globalThis, key, {
  configurable: true,
  value: key === 'getComputedStyle' ? dom.window.getComputedStyle.bind(dom.window) : dom.window[key],
})
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true, value: dom.window.localStorage,
})
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
test.after(async () => { await server.close(); dom.window.close() })

const testing = await import('@testing-library/react')
const userEvent = (await import('@testing-library/user-event')).default
const axe = (await import('axe-core')).default
const { render, screen, cleanup, fireEvent, waitFor } = testing
test.afterEach(() => { cleanup(); localStorage.clear() })

test('ConfirmDialog resolves FIFO requests with an activation boundary and Escape cancellation', async () => {
  const {
    ConfirmDialogProvider, useConfirmDialog,
  } = await server.ssrLoadModule('/src/components/common/ConfirmDialog.jsx')
  const outcomes = []
  function Harness() {
    const confirm = useConfirmDialog()
    const queue = () => {
      confirm({ title: 'First', message: 'first request' }).then((value) => outcomes.push(value))
      confirm({ title: 'Second', message: 'second request' }).then((value) => outcomes.push(value))
    }
    return React.createElement('button', { onClick: queue }, 'Queue confirmations')
  }
  const user = userEvent.setup({ document })
  render(React.createElement(ConfirmDialogProvider, null, React.createElement(Harness)))
  await user.click(screen.getByRole('button', { name: 'Queue confirmations' }))
  assert.equal(screen.getByRole('alertdialog').getAttribute('aria-modal'), 'true')
  assert.ok(screen.getByRole('heading', { name: 'First' }))
  await user.click(screen.getByRole('button', { name: 'Confirm' }))
  assert.equal(screen.queryByRole('alertdialog'), null, 'next dialog must not activate on the same click')
  await waitFor(() => assert.ok(screen.getByRole('heading', { name: 'Second' })), { timeout: 1000 })
  fireEvent.keyDown(window, { key: 'Escape' })
  await waitFor(() => assert.deepEqual(outcomes, [true, false]))
})

test('dialogs reset prompts, cancel on backdrop, restore focus, and settle on provider unmount', async () => {
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true, get() { return this.hidden ? null : document.body },
  })
  const {
    ConfirmDialogProvider, useConfirmDialog, usePromptDialog,
  } = await server.ssrLoadModule('/src/components/common/ConfirmDialog.jsx')
  const outcomes = []
  function Harness() {
    const confirm = useConfirmDialog()
    const prompt = usePromptDialog()
    return React.createElement(React.Fragment, null,
      React.createElement('button', { onClick: async () => {
        outcomes.push(await prompt({ title: 'Name one', defaultValue: 'first' }))
        outcomes.push(await prompt({ title: 'Name two', defaultValue: 'second' }))
      } }, 'Prompt twice'),
      React.createElement('button', { onClick: () => {
        confirm({ message: 'active' }).then((value) => outcomes.push(value))
        prompt({ title: 'queued' }).then((value) => outcomes.push(value))
      } }, 'Queue then unmount'))
  }
  const user = userEvent.setup({ document })
  const mounted = render(React.createElement(ConfirmDialogProvider, null, React.createElement(Harness)))
  const opener = screen.getByRole('button', { name: 'Prompt twice' })
  opener.focus()
  await user.click(opener)
  const firstInput = screen.getByRole('textbox', { name: 'Value' })
  assert.equal(firstInput.value, 'first')
  await user.clear(firstInput); await user.type(firstInput, 'edited')
  fireEvent.mouseDown(screen.getByRole('dialog').parentElement)
  await waitFor(() => assert.equal(screen.queryByRole('dialog'), null))
  assert.equal(document.activeElement, opener)
  await waitFor(() => assert.ok(screen.getByRole('heading', { name: 'Name two' })), { timeout: 1000 })
  assert.equal(screen.getByRole('textbox', { name: 'Value' }).value, 'second')
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  await waitFor(() => assert.deepEqual(outcomes.slice(0, 2), [null, null]))
  await user.click(screen.getByRole('button', { name: 'Queue then unmount' }))
  mounted.unmount()
  await waitFor(() => assert.deepEqual(outcomes.slice(-2), [false, null]))
})

test('LockableSlider persists its lock and only emits changes while unlocked', async () => {
  const { default: LockableSlider } = await server.ssrLoadModule(
    '/src/components/shared/LockableSlider.jsx')
  const values = []
  const user = userEvent.setup({ document })
  render(React.createElement(LockableSlider, {
    label: 'Identity strength', value: 0.5, min: 0, max: 1, step: 0.1,
    storageKey: 'identity-lock', onChange: (event) => values.push(event.target.value),
  }))
  const slider = screen.getByRole('slider', { name: 'Identity strength' })
  assert.equal(slider.disabled, true)
  await user.click(screen.getByRole('button', { name: 'Unlock Identity strength' }))
  assert.equal(slider.disabled, false)
  assert.equal(localStorage.getItem('identity-lock'), 'false')
  fireEvent.change(slider, { target: { value: '0.7' } })
  assert.deepEqual(values, ['0.7'])
})

test('Markdown renders semantic headings, links, lists and validated tables', async () => {
  const { default: Markdown } = await server.ssrLoadModule('/src/components/common/Markdown.jsx')
  render(React.createElement(Markdown, { source: [
    '# Guide', '## Same', '## Same', '- item', '[Docs](https://example.com)',
    '| A | B |\n| --- | --- |\n| 1 | 2 |',
  ].join('\n\n'), variant: 'guide' }))
  const headings = screen.getAllByRole('heading', { level: 2 })
  assert.deepEqual(headings.map((heading) => heading.closest('section')?.id), ['same', 'same-2'])
  const docsLink = screen.getByRole('link', { name: 'Docs' })
  assert.equal(docsLink.getAttribute('href'), 'https://example.com')
  assert.equal(docsLink.getAttribute('target'), '_blank')
  assert.equal(docsLink.getAttribute('rel'), 'noreferrer')
  assert.ok(screen.getByRole('list'))
  assert.equal(screen.getAllByRole('row').length, 2)
})

test('Markdown resolves opted-in links as same-document navigation', async () => {
  const { default: Markdown } = await server.ssrLoadModule('/src/components/common/Markdown.jsx')
  render(React.createElement(Markdown, {
    source: '[Guide](using-the-app.md) [Docs](https://example.com)',
    resolveLink: (href) => href === 'using-the-app.md' ? '#/guide/using-the-app' : null,
  }))
  const guideLink = screen.getByRole('link', { name: 'Guide' })
  assert.equal(guideLink.getAttribute('href'), '#/guide/using-the-app')
  assert.equal(guideLink.hasAttribute('target'), false)
  assert.equal(guideLink.hasAttribute('rel'), false)
  const docsLink = screen.getByRole('link', { name: 'Docs' })
  assert.equal(docsLink.getAttribute('target'), '_blank')
  assert.equal(docsLink.getAttribute('rel'), 'noreferrer')
})

test('every guide link resolves to a chapter route or an absolute external URL', async () => {
  const { ALL_GUIDE_CHAPTERS, GUIDE_DOCUMENT_ROUTES, resolveGuideLink } =
    await server.ssrLoadModule('/src/pages/GuidePage.jsx')
  const chapterRoutes = new Set(ALL_GUIDE_CHAPTERS.map((chapter) =>
    chapter.id === 'getting-help' ? '/help' : `/guide/${chapter.id}`))
  for (const route of Object.values(GUIDE_DOCUMENT_ROUTES)) {
    assert.ok(chapterRoutes.has(route), `guide document maps to unknown route ${route}`)
  }
  const linkPattern = /\[[^\]]+\]\(([^)]+)\)/g
  for (const chapter of ALL_GUIDE_CHAPTERS) {
    for (const match of chapter.source.matchAll(linkPattern)) {
      const href = match[1]
      const resolved = resolveGuideLink(href)
      assert.ok(
        (resolved && chapterRoutes.has(resolved.slice(1))) || /^https?:\/\//.test(href),
        `${chapter.id} has no in-app route for ${href}`,
      )
    }
  }
})

test('every shipped guide chapter renders semantic content without axe violations', async () => {
  const { default: Markdown } = await server.ssrLoadModule('/src/components/common/Markdown.jsx')
  const { ALL_GUIDE_CHAPTERS } = await server.ssrLoadModule('/src/pages/GuidePage.jsx')
  assert.equal(ALL_GUIDE_CHAPTERS.length, 24)
  for (const chapter of ALL_GUIDE_CHAPTERS) {
    const mounted = render(React.createElement('main', { 'aria-label': chapter.title },
      React.createElement(Markdown, { source: chapter.source, variant: 'guide' })))
    assert.equal(mounted.container.querySelectorAll('h1').length, 0, `${chapter.id} must leave the page H1 to GuidePage`)
    assert.ok(mounted.container.querySelectorAll('h1,h2,h3').length > 0, chapter.id)
    const ids = [...mounted.container.querySelectorAll('[id]')].map((node) => node.id)
    assert.equal(new Set(ids).size, ids.length, `duplicate heading target in ${chapter.id}`)
    const result = await axe.run(mounted.container, { rules: { 'color-contrast': { enabled: false } } })
    assert.deepEqual(result.violations.map((violation) => violation.id), [], chapter.id)
    mounted.unmount()
  }
})

test('the beginner guide exposes one ordered product step per page', async () => {
  const { FIRST_RUN_STEPS } = await server.ssrLoadModule('/src/pages/GuidePage.jsx')
  assert.equal(FIRST_RUN_STEPS.length, 21)
  assert.deepEqual(
    FIRST_RUN_STEPS.map((chapter) => chapter.num),
    Array.from({ length: 21 }, (_, index) => String(index + 1).padStart(2, '0')),
  )
  for (const chapter of FIRST_RUN_STEPS) {
    assert.equal(chapter.group, 'First run')
    const topLevelHeadings = [...chapter.source.matchAll(/^# (.+)$/gm)]
    assert.equal(topLevelHeadings.length, 1, `${chapter.id} must contain one page title`)
    assert.match(topLevelHeadings[0][0], new RegExp(`^# Step ${Number(chapter.num)}:`))
    assert.match(chapter.source, /## Do this/)
    assert.match(chapter.source, /## You are finished when/)
  }
  for (const id of ['review-corpus', 'choose-anchors', 'plan-coverage', 'primary-reference', 'generate-gaps']) {
    const source = FIRST_RUN_STEPS.find((chapter) => chapter.id === id).source
    assert.match(source, /Concept/, `${id} must explain the Concept path`)
    assert.match(source, /Style/, `${id} must explain the Style path`)
  }
  assert.match(FIRST_RUN_STEPS.find((chapter) => chapter.id === 'review-checkpoints').source, /Import →/)

  const gettingStarted = FIRST_RUN_STEPS.find((chapter) => chapter.id === 'getting-started').source
  assert.match(gettingStarted, /python3 --version/)
  assert.match(gettingStarted, /Python 3\.11 or 3\.12/)
  assert.match(gettingStarted, /Skip setup — I'll do it later/)

  const provider = FIRST_RUN_STEPS.find((chapter) => chapter.id === 'image-provider').source
  assert.match(provider, /Nano Banana provider/)
  assert.match(provider, /select \*\*Google direct\*\*.*\*\*Replicate\*\*/)
  assert.match(provider, /OpenAI does not use this selector/)
  assert.match(provider, /API billing are separate from a ChatGPT subscription/)

  const comfyui = FIRST_RUN_STEPS.find((chapter) => chapter.id === 'comfyui').source
  assert.match(comfyui, /`models` and `custom_nodes`/)

  const localVision = FIRST_RUN_STEPS.find((chapter) => chapter.id === 'local-vision').source
  assert.match(localVision, /required to advance once you enter Setup/)
  assert.match(localVision, /Skip setup — I'll do it later/)
  assert.doesNotMatch(localVision, /continue without configuring/)

  const curation = FIRST_RUN_STEPS.find((chapter) => chapter.id === 'curate-images').source
  assert.match(curation, /Find watermarks/)
  assert.match(curation, /Review flagged \(N\)/)

  const captions = FIRST_RUN_STEPS.find((chapter) => chapter.id === 'caption-images').source
  assert.match(captions, /Style datasets have no automatic style-term scanner/)

  const exportGuide = FIRST_RUN_STEPS.find((chapter) => chapter.id === 'export-dataset').source
  assert.match(exportGuide, /continue to Step 21/)

  const backup = FIRST_RUN_STEPS.find((chapter) => chapter.id === 'back-up').source
  assert.match(backup, /does not include raw training-run folders/)
  assert.match(backup, /\.safetensors/)
  assert.match(backup, /separately copy/)
  assert.match(backup, /Download the cloud-trained LoRA/)
  assert.match(backup, /Download image/)
  assert.match(backup, /5,000 image records/)
  assert.match(backup, /Copy the entire `data` folder/)
})

test('guide heading routes preserve page ownership and the desktop rail follows the active item', async () => {
  const { guideHeadingRoute, keepGuideItemVisible } = await server.ssrLoadModule('/src/pages/GuidePage.jsx')
  assert.equal(
    guideHeadingRoute('image-provider', 'before-you-begin'),
    '/guide/image-provider?heading=before-you-begin',
  )
  assert.equal(
    guideHeadingRoute('local-vision', 'server & model'),
    '/guide/local-vision?heading=server%20%26%20model',
  )
  assert.equal(
    guideHeadingRoute('getting-help', 'create-a-report'),
    '/help?heading=create-a-report',
  )
  const nav = { scrollTop: 20, getBoundingClientRect: () => ({ top: 100, bottom: 500 }) }
  keepGuideItemVisible(nav, { getBoundingClientRect: () => ({ top: 480, bottom: 540 }) })
  assert.equal(nav.scrollTop, 60)
  keepGuideItemVisible(nav, { getBoundingClientRect: () => ({ top: 70, bottom: 110 }) })
  assert.equal(nav.scrollTop, 30)
})

test('guide heading focus uses instant scrolling when reduced motion is requested', async () => {
  const { focusGuideHeading } = await server.ssrLoadModule('/src/pages/GuidePage.jsx')
  const heading = document.createElement('h2')
  heading.id = 'reduced-motion-heading'
  let scrollOptions = null
  heading.scrollIntoView = (options) => { scrollOptions = options }
  document.body.appendChild(heading)
  const originalMatchMedia = window.matchMedia
  window.matchMedia = () => ({ matches: true })
  try {
    assert.equal(focusGuideHeading(heading.id), true)
    assert.equal(document.activeElement, heading)
    assert.deepEqual(scrollOptions, { behavior: 'auto', block: 'start' })
  } finally {
    window.matchMedia = originalMatchMedia
    heading.remove()
  }
})

test('Studio result preview offers a real image download', async () => {
  const { default: ResultLightbox } = await server.ssrLoadModule(
    '/src/components/dataset/studio/ResultLightbox.jsx')
  render(React.createElement(ResultLightbox, {
    img: {
      id: 7, filename: 'studio result #1.png', label: 'Checkpoint 1000',
      strength: 0.8, rating: 0, seed: 42,
    },
    datasetId: 12,
    onRate() {},
    onClose() {},
    fmt: (value) => String(value),
  }))
  const download = screen.getByRole('link', { name: 'Download image' })
  assert.equal(download.getAttribute('href'), '/api/dataset/12/img/studio%20result%20%231.png')
  assert.equal(download.getAttribute('download'), 'studio result #1.png')
})

test('focus trap enters, loops in both directions, and restores prior focus', async () => {
  const { useRef, useState } = React
  const { useFocusTrap } = await server.ssrLoadModule('/src/hooks/useFocusTrap.js')
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true, get() { return this.hidden ? null : document.body },
  })
  function Harness() {
    const [open, setOpen] = useState(false)
    const ref = useRef(null)
    useFocusTrap(ref, open)
    return React.createElement(React.Fragment, null,
      React.createElement('button', { onClick: () => setOpen(true) }, 'Open trap'),
      open && React.createElement('div', { ref, role: 'dialog' },
        React.createElement('button', null, 'First'),
        React.createElement('button', null, 'Last'),
        React.createElement('button', { onClick: () => setOpen(false) }, 'Close trap')))
  }
  const user = userEvent.setup({ document })
  render(React.createElement(Harness))
  const opener = screen.getByRole('button', { name: 'Open trap' })
  opener.focus()
  await user.click(opener)
  assert.equal(document.activeElement, screen.getByRole('button', { name: 'First' }))
  screen.getByRole('button', { name: 'Close trap' }).focus()
  await user.keyboard('{Tab}')
  assert.equal(document.activeElement, screen.getByRole('button', { name: 'First' }))
  await user.keyboard('{Shift>}{Tab}{/Shift}')
  assert.equal(document.activeElement, screen.getByRole('button', { name: 'Close trap' }))
  await user.click(screen.getByRole('button', { name: 'Close trap' }))
  assert.equal(document.activeElement, opener)
})

test('shared model, resolution, and LoRA controls reconcile storage and keyboard state', async () => {
  const { CapabilitiesProvider } = await server.ssrLoadModule('/src/context/CapabilitiesContext.jsx')
  const { default: FluxPicker } = await server.ssrLoadModule('/src/components/shared/Flux2KleinModelPicker.jsx')
  const { default: ResolutionSelector } = await server.ssrLoadModule('/src/components/shared/ResolutionSelector.jsx')
  const { default: ZImageLoraConfig } = await server.ssrLoadModule('/src/components/shared/ZImageLoraConfig.jsx')
  localStorage.setItem('editPage_flux2KleinModel_v1', 'missing.safetensors')
  localStorage.setItem('mounted-loras', JSON.stringify({
    'person.safetensors': { enabled: true, strength: 9, locked: false },
  }))
  globalThis.fetch = async () => new Response(JSON.stringify({
    comfyui: { models: { klein: ['alpha.safetensors', 'beta.safetensors'] } },
    resolution_metadata: {
      tiers: [{ value: 'fast', label: 'Fast' }, { value: 'standard', label: 'Standard' }],
      profiles: { default: { square: { fast: [512, 512], standard: [1024, 1024] } } },
    },
  }), { status: 200, headers: { 'content-type': 'application/json' } })
  const models = []; const resolutions = []; const stacks = []
  const mounted = render(React.createElement(CapabilitiesProvider, null,
    React.createElement(FluxPicker, { onChange: (value) => models.push(value) }),
    React.createElement(ResolutionSelector, {
      value: 'fast', onChange: (value) => resolutions.push(value), label: 'Output resolution',
    }),
    React.createElement(ZImageLoraConfig, {
      storageKey: 'mounted-loras', onChange: (value) => stacks.push(value),
      loras: [{ filename: 'person.safetensors', displayName: 'Person', triggerWord: 'person' }],
    })))
  await waitFor(() => assert.ok(screen.getByRole('combobox', { name: 'Base model' })))
  assert.equal(screen.getByRole('combobox', { name: 'Base model' }).value, 'alpha.safetensors')
  assert.equal(localStorage.getItem('editPage_flux2KleinModel_v1'), 'alpha.safetensors')
  fireEvent.keyDown(screen.getByRole('radiogroup', { name: 'Output resolution' }), { key: 'ArrowRight' })
  assert.deepEqual(resolutions, ['standard'])
  await waitFor(() => assert.equal(screen.getByRole('slider', { name: 'Strength of Person' }).value, '2'))
  assert.equal(stacks.at(-1)[0].strength, 2)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Enable Person' }))
  await waitFor(() => assert.deepEqual(stacks.at(-1), []))
  assert.ok(models.includes('alpha.safetensors'))
  const audit = await axe.run(mounted.container, { rules: { 'color-contrast': { enabled: false } } })
  assert.deepEqual(audit.violations.map((violation) => violation.id), [])
})

test('stacked modal locks release independently and restore focus after final cleanup', async () => {
  const { useRef, useState } = React
  const { useFocusTrap } = await server.ssrLoadModule('/src/hooks/useFocusTrap.js')
  const { useBodyScrollLock } = await server.ssrLoadModule('/src/hooks/useBodyScrollLock.js')
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true, get() { return this.hidden ? null : document.body },
  })
  function Modal({ name, close }) {
    const ref = useRef(null); useFocusTrap(ref, true); useBodyScrollLock(true)
    return React.createElement('section', { ref, role: 'dialog', 'aria-label': name },
      React.createElement('button', { onClick: close }, `Close ${name}`))
  }
  function Harness() {
    const [first, setFirst] = useState(false); const [second, setSecond] = useState(false)
    return React.createElement(React.Fragment, null,
      React.createElement('button', { onClick: () => setFirst(true) }, 'Open first'),
      first && React.createElement(Modal, { name: 'first', close: () => setFirst(false) }),
      React.createElement('button', { onClick: () => setSecond(true) }, 'Open second'),
      second && React.createElement(Modal, { name: 'second', close: () => setSecond(false) }))
  }
  const user = userEvent.setup({ document }); render(React.createElement(Harness))
  const opener = screen.getByRole('button', { name: 'Open first' }); opener.focus()
  await user.click(opener); await user.click(screen.getByRole('button', { name: 'Open second' }))
  assert.equal(document.body.style.overflow, 'hidden')
  await user.click(screen.getByRole('button', { name: 'Close second' }))
  assert.equal(document.body.style.overflow, 'hidden', 'first modal still owns the lock')
  await user.click(screen.getByRole('button', { name: 'Close first' }))
  assert.equal(document.body.style.overflow, '')
  assert.equal(document.activeElement, opener)
})

test('assembled VariationCatalog retries, persists custom shots, reconciles duplicates, and launches', async () => {
  const { CapabilitiesProvider } = await server.ssrLoadModule('/src/context/CapabilitiesContext.jsx')
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { ConfirmDialogProvider } = await server.ssrLoadModule('/src/components/common/ConfirmDialog.jsx')
  const { default: VariationCatalog } = await server.ssrLoadModule(
    '/src/components/dataset/VariationCatalog.jsx')
  let catalogCalls = 0
  globalThis.fetch = async (url) => {
    const target = String(url)
    if (target.endsWith('/api/capabilities')) return new Response(JSON.stringify({
      configured: true, engines: { klein: true }, comfyui: { reachable: true, models: { klein: ['base.safetensors'] } },
      privacy: { allow_remote_generation: false }, generation_pricing: { per_image: {} },
    }), { status: 200, headers: { 'content-type': 'application/json' } })
    if (target.endsWith('/api/settings')) return new Response(JSON.stringify({
      config: { engines: { enabled: ['klein'] }, privacy: { allow_remote_generation: false } }, secrets: {},
    }), { status: 200, headers: { 'content-type': 'application/json' } })
    if (target.endsWith('/api/dataset/variations')) {
      catalogCalls += 1
      if (catalogCalls === 1) return new Response(JSON.stringify({ error: 'temporary' }), {
        status: 503, headers: { 'content-type': 'application/json' },
      })
      return new Response(JSON.stringify({
        catalog: [{ id: 'portrait', label: 'Portrait', prompt: 'portrait prompt', framing: 'face' }],
        nsfw_catalog: [], presets: { balanced: ['portrait'] },
      }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request ${target}`)
  }
  localStorage.setItem('datasetGenerator', 'klein')
  const launches = []
  render(React.createElement(ToastProvider, null,
    React.createElement(ConfirmDialogProvider, null,
      React.createElement(CapabilitiesProvider, null,
        React.createElement(VariationCatalog, {
          hasRef: true, hasPrimaryRef: true, busy: false,
          onGenerate: (...args) => launches.push(args), images: [],
        })))))
  await waitFor(() => assert.ok(screen.getByText('Variation catalog could not be loaded.')))
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => assert.ok(screen.getByRole('button', { name: /Portrait/ })))
  fireEvent.click(screen.getByRole('button', { name: /Portrait/ }))
  fireEvent.click(screen.getByText('✨ Custom shot'))
  fireEvent.change(screen.getByRole('textbox', { name: /Describe outfit/ }), {
    target: { value: 'night portrait under neon lights' },
  })
  fireEvent.click(screen.getByRole('button', { name: /Add/ }))
  assert.match(localStorage.getItem('datasetCustomShots'), /night portrait/)
  fireEvent.click(screen.getByRole('button', { name: /Generate \(2\)/ }))
  assert.equal(launches.length, 1)
  assert.deepEqual(launches[0][0].map((shot) => shot.id), ['portrait', launches[0][0][1].id])
})

test('assembled SetupPage recovers its initial request and reports autodetection failure', async () => {
  const { MemoryRouter } = await server.ssrLoadModule('react-router-dom')
  const { CapabilitiesProvider } = await server.ssrLoadModule('/src/context/CapabilitiesContext.jsx')
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { ConfirmDialogProvider } = await server.ssrLoadModule('/src/components/common/ConfirmDialog.jsx')
  const { default: SetupPage } = await server.ssrLoadModule('/src/pages/SetupPage.jsx')
  let settingsCalls = 0
  const config = {
    engines: { enabled: [] }, privacy: { allow_remote_generation: false },
    ollama: { url: '', vision_model: '' }, comfyui: { api_url: '', base_dir: '' },
    training: { aitoolkit_dir: '' },
  }
  globalThis.fetch = async (url) => {
    const target = String(url)
    if (target.endsWith('/api/capabilities')) return new Response(JSON.stringify({
      configured: true, engines: {}, comfyui: {}, ollama: {}, generation_pricing: { per_image: {} },
    }), { status: 200, headers: { 'content-type': 'application/json' } })
    if (target.endsWith('/api/settings')) {
      settingsCalls += 1
      if (settingsCalls === 1) return new Response(JSON.stringify({ error: 'offline' }), {
        status: 503, headers: { 'content-type': 'application/json' },
      })
      return new Response(JSON.stringify({ config, secrets: {} }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    if (target.endsWith('/api/setup/autodetect')) return new Response(JSON.stringify({ error: 'scan failed' }), {
      status: 503, headers: { 'content-type': 'application/json' },
    })
    throw new Error(`Unexpected request ${target}`)
  }
  render(React.createElement(MemoryRouter, null,
    React.createElement(ToastProvider, null,
      React.createElement(ConfirmDialogProvider, null,
        React.createElement(CapabilitiesProvider, null, React.createElement(SetupPage))))))
  await waitFor(() => assert.ok(screen.getByText("Couldn't load setup.")))
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => assert.ok(screen.getByRole('heading', { name: 'Setup', level: 1 })))
  await waitFor(() => assert.ok(screen.getByText(/Machine scan failed:/)))
  assert.equal(screen.getAllByText(/Step \d of 5/).length, 5)
  for (const label of [
    /Cloud\/API image provider/,
    /Local image provider — ComfyUI/,
    /Local vision — Ollama/,
    /Quality tools — ML extras/,
    /LoRA training — ai-toolkit/,
  ]) assert.ok(screen.getByText(label))
  assert.ok(screen.getByRole('button', { name: 'Retry scan' }))
})

test('setup local vision selector exposes provider-specific fields without stale readiness', async () => {
  const { default: SetupToolBody } = await server.ssrLoadModule(
    '/src/components/setup/SetupToolBody.jsx')
  const user = userEvent.setup({ document })
  const changes = []
  let saves = 0
  const stepById = {
    ollama: {
      provider: 'ollama', providerLabel: 'Ollama', status: 'ready', reachable: true,
      visionModelReady: true, url: 'http://127.0.0.1:11434', visionModel: 'ollama-vl',
      installed: true,
    },
  }
  function Harness() {
    const [config, setConfig] = React.useState({
      local_vision: { backend: 'ollama' },
      ollama: { url: 'http://127.0.0.1:11434', vision_model: 'ollama-vl' },
      lmstudio: { url: 'http://127.0.0.1:1234/v1', vision_model: '' },
      llamacpp: { url: 'http://127.0.0.1:8080/v1', vision_model: '' },
    })
    const setField = (section, key, value) => {
      changes.push([section, key, value])
      setConfig((current) => ({
        ...current, [section]: { ...current[section], [key]: value },
      }))
    }
    return React.createElement(SetupToolBody, {
      id: 'ollama', stepById, config, setField,
      secretsPresence: {}, setSecretsPresence: () => {},
      secretInputs: {}, setSecretInputs: () => {}, detected: {}, busy: false, caps: {},
      refresh: async () => {}, toast: { success() {}, warning() {}, error() {} },
      persist: async () => { saves += 1 }, applyDetectedPath: () => {},
    })
  }

  render(React.createElement(Harness))
  await user.selectOptions(screen.getByLabelText('Local vision backend'), 'lmstudio')

  assert.ok(screen.getByText(/Backend not checked yet/))
  assert.ok(screen.getByLabelText('LM Studio OpenAI-compatible URL'))
  const model = screen.getByLabelText('LM Studio vision model')
  await user.type(model, 'qwen-vl')
  assert.deepEqual(changes.at(-1), ['lmstudio', 'vision_model', 'qwen-vl'])
  await user.click(screen.getByRole('button', { name: 'Save & re-check' }))
  assert.equal(saves, 1)
  assert.equal(screen.queryByText(/Ollama is running at/), null)
})

test('session tool details give exact local launch instructions', async () => {
  const { default: SetupToolBody } = await server.ssrLoadModule(
    '/src/components/setup/SetupToolBody.jsx')
  const common = {
    secretsPresence: {}, setSecretsPresence() {}, secretInputs: {}, setSecretInputs() {},
    detected: { host: { platform: 'darwin' } }, busy: false, caps: {}, refresh: async () => {},
    toast: { success() {}, warning() {}, error() {} }, setField() {}, persist: async () => {},
    applyDetectedPath() {}, mode: 'session',
  }
  const config = {
    comfyui: { api_url: 'http://127.0.0.1:8188',
      base_dir: '/Users/test/ComfyUI-Installs/ComfyUI-desktop/ComfyUI' },
    local_vision: { backend: 'lmstudio' },
    lmstudio: { url: 'http://127.0.0.1:1234/v1', vision_model: 'qwen-vl' },
  }
  const stepById = {
    comfyui: { reachable: false, hasKlein: true, dirValid: true,
      resolvedDir: '/Users/test/ComfyUI-Installs/ComfyUI-desktop/ComfyUI',
      baseDir: '/Users/test/ComfyUI-Installs/ComfyUI-desktop/ComfyUI',
      folderLauncher: { cwd: '/Users/test/ComfyUI-Installs/ComfyUI-desktop/ComfyUI',
        command: './.venv/bin/python main.py --listen 127.0.0.1 --port 8188',
        managedByDesktop: true },
      app: { name: 'Comfy Desktop', path: '/Applications/Comfy Desktop.app',
        launchCommand: 'open -b com.todesktop.241012ess7yxs0e' } },
    ollama: { provider: 'lmstudio', providerLabel: 'LM Studio', reachable: false,
      visionModelReady: false, url: config.lmstudio.url, visionModel: 'qwen-vl' },
  }

  const comfy = render(React.createElement(SetupToolBody, {
    ...common, id: 'comfyui', config, stepById,
  }))
  assert.ok(screen.getByRole('heading', { name: 'Start ComfyUI now' }))
  assert.equal(screen.queryByText('./.venv/bin/python main.py --listen 127.0.0.1 --port 8188'), null)
  assert.ok(screen.getByText('open -b com.todesktop.241012ess7yxs0e'))
  assert.ok(screen.getByText(/This is a Comfy Desktop-managed installation/))
  assert.ok(screen.getByText('/Applications/Comfy Desktop.app'))
  assert.ok(screen.getByText((_, node) => node?.tagName === 'LI'
    && /select your existing instance\s+named\s+ComfyUI/.test(node.textContent)))
  assert.ok(screen.getAllByText('/Users/test/ComfyUI-Installs/ComfyUI-desktop/ComfyUI').length >= 1)
  assert.ok(screen.getByText((_, node) => node?.tagName === 'LI'
    && /Then come back here and select\s+Re-check now/.test(node.textContent)))
  comfy.unmount()

  render(React.createElement(SetupToolBody, {
    ...common, id: 'ollama', config, stepById,
  }))
  assert.ok(screen.getByRole('heading', { name: 'Start LM Studio now' }))
  assert.ok(screen.getByText('open -a "LM Studio"'))
  assert.ok(screen.getByText('lms server start --port 1234'))
  assert.ok(screen.getByText((_, node) => node?.tagName === 'LI'
    && /open the\s+Developer\s+tab/.test(node.textContent)))
  assert.ok(screen.getByText(/Choose and load this vision model/))
})

test('a running ComfyUI session does not ask the user to start it', async () => {
  const { default: SetupToolBody } = await server.ssrLoadModule(
    '/src/components/setup/SetupToolBody.jsx')
  render(React.createElement(SetupToolBody, {
    id: 'comfyui', mode: 'session',
    stepById: { comfyui: {
      reachable: true, runtimeReady: true, installLabel: 'ComfyUI Desktop',
      apiUrl: 'http://127.0.0.1:8188', resolvedDir: '/Users/test/ComfyUI',
    } },
    config: { comfyui: { base_dir: '/Users/test/ComfyUI', api_url: 'http://127.0.0.1:8188' } },
    secretsPresence: {}, setSecretsPresence() {}, secretInputs: {}, setSecretInputs() {},
    detected: { host: { platform: 'darwin' } }, busy: false, caps: {}, refresh: async () => {},
    toast: { success() {}, warning() {}, error() {} }, setField() {}, persist: async () => {},
    applyDetectedPath() {},
  }))

  assert.ok(screen.getByRole('heading', { name: 'ComfyUI Desktop is running' }))
  assert.ok(screen.getByText(/Nothing needs to be started/))
  assert.equal(screen.queryByRole('heading', { name: 'Start ComfyUI now' }), null)
  assert.equal(screen.queryByText(/does not contain a detected Python environment/), null)
})

test('setup image step renders independent provider credentials and changes Nano Banana provider', async () => {
  const { default: SetupToolBody } = await server.ssrLoadModule(
    '/src/components/setup/SetupToolBody.jsx')
  const user = userEvent.setup({ document })
  const changes = []
  function Harness() {
    const [config, setConfig] = React.useState({
      engines: { nanobanana_provider: 'google' },
    })
    const setField = (section, key, value) => {
      changes.push([section, key, value])
      setConfig((current) => ({
        ...current, [section]: { ...current[section], [key]: value },
      }))
    }
    return React.createElement(SetupToolBody, {
      id: 'image', stepById: { image: { engines: {} } }, config, setField,
      secretsPresence: {
        GEMINI_API_KEY: true, REPLICATE_API_TOKEN: false, OPENAI_API_KEY: true,
      },
      setSecretsPresence: () => {}, secretInputs: {}, setSecretInputs: () => {},
      detected: {}, busy: false, caps: {}, refresh: async () => {},
      toast: { success() {}, warning() {}, error() {} }, persist: async () => {},
      applyDetectedPath: () => {},
    })
  }

  render(React.createElement(Harness))

  assert.ok(screen.getByLabelText('Gemini API key'))
  assert.ok(screen.getByLabelText('Replicate API token'))
  assert.ok(screen.getByLabelText('OpenAI API key'))
  assert.equal(screen.getAllByText('✓ Saved').length, 2)
  assert.equal(screen.getAllByText('○ Not set').length, 1)
  await user.selectOptions(screen.getByLabelText('Nano Banana provider'), 'replicate')
  assert.deepEqual(changes.at(-1), ['engines', 'nanobanana_provider', 'replicate'])
})

test('setup ComfyUI recovery names classic and Desktop directory layouts', async () => {
  const { default: SetupToolBody } = await server.ssrLoadModule(
    '/src/components/setup/SetupToolBody.jsx')
  render(React.createElement(SetupToolBody, {
    id: 'comfyui',
    stepById: {
      comfyui: {
        baseDir: '/Applications/ComfyUI', dirValid: false, reachable: false,
        hasKlein: false, apiUrl: 'http://127.0.0.1:8188',
      },
    },
    config: {
      comfyui: {
        base_dir: '/Applications/ComfyUI', api_url: 'http://127.0.0.1:8188',
      },
    },
    secretsPresence: {}, setSecretsPresence() {}, secretInputs: {}, setSecretInputs() {},
    detected: {
      host: { platform: 'darwin' },
      comfyui: { app: { name: 'Comfy Desktop', path: '/Applications/Comfy Desktop.app',
        launch_command: 'open -b com.todesktop.241012ess7yxs0e' } },
    }, busy: false, caps: {}, refresh: async () => {},
    toast: { success() {}, warning() {}, error() {} }, setField() {}, persist: async () => {},
    applyDetectedPath() {},
  }))
  assert.ok(screen.getByText('main.py'))
  assert.ok(screen.getByText('custom_nodes/'))
  assert.ok(screen.getAllByText(/Desktop/).length >= 1)
  assert.ok(screen.getByText('Choose one installation method'))
  assert.ok(screen.getByRole('heading', { name: 'Comfy Desktop' }))
  assert.ok(screen.getByRole('heading', { name: 'Git / manual installation' }))
  assert.equal(screen.getByRole('link', { name: 'Download Comfy Desktop →' })
    .getAttribute('href'), 'https://www.comfy.org/download')
  assert.ok(screen.getByText('open -b com.todesktop.241012ess7yxs0e'))
  assert.ok(screen.getByText('git clone https://github.com/comfyanonymous/ComfyUI'))
  assert.ok(screen.getByText('python3 -m venv .venv'))
  assert.ok(screen.getByText('python -m pip install -r requirements.txt'))
  assert.ok(screen.getByText('python main.py --listen 127.0.0.1 --port 8188'))
})

test('setup ComfyUI identifies which installation method owns the configured folder', async () => {
  const { default: SetupToolBody } = await server.ssrLoadModule(
    '/src/components/setup/SetupToolBody.jsx')
  render(React.createElement(SetupToolBody, {
    id: 'comfyui',
    stepById: {
      comfyui: {
        baseDir: '/Users/test/ComfyUI', resolvedDir: '/Users/test/ComfyUI',
        dirValid: true, reachable: true, hasKlein: true,
        folderLauncher: { managedByDesktop: true },
      },
    },
    config: { comfyui: { base_dir: '/Users/test/ComfyUI', api_url: 'http://127.0.0.1:8188' } },
    secretsPresence: {}, setSecretsPresence() {}, secretInputs: {}, setSecretInputs() {},
    detected: { host: { platform: 'darwin' } }, busy: false, caps: {}, refresh: async () => {},
    toast: { success() {}, warning() {}, error() {} }, setField() {}, persist: async () => {},
    applyDetectedPath() {},
  }))

  assert.ok(screen.getByText((_, node) => node?.tagName === 'P'
    && /Detected installation type:\s*Comfy Desktop-managed/.test(node.textContent)))
})

test('assembled SettingsPage recovers an initial settings request failure', async () => {
  const { MemoryRouter } = await server.ssrLoadModule('react-router-dom')
  const { CapabilitiesProvider } = await server.ssrLoadModule('/src/context/CapabilitiesContext.jsx')
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { ConfirmDialogProvider } = await server.ssrLoadModule('/src/components/common/ConfirmDialog.jsx')
  const { default: SettingsPage } = await server.ssrLoadModule('/src/pages/SettingsPage.jsx')
  let settingsCalls = 0
  globalThis.fetch = async (url) => {
    const target = String(url)
    if (target.endsWith('/api/capabilities')) return new Response(JSON.stringify({
      configured: true, engines: {}, comfyui: {}, ollama: {}, captioners: {},
    }), { status: 200, headers: { 'content-type': 'application/json' } })
    if (target.endsWith('/api/settings')) {
      settingsCalls += 1
      if (settingsCalls === 1) return new Response(JSON.stringify({ error: 'offline' }), {
        status: 503, headers: { 'content-type': 'application/json' },
      })
      return new Response(JSON.stringify({ config: {}, secrets: {}, runtime: {} }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request ${target}`)
  }
  render(React.createElement(MemoryRouter, null,
    React.createElement(ToastProvider, null,
      React.createElement(ConfirmDialogProvider, null,
        React.createElement(CapabilitiesProvider, null, React.createElement(SettingsPage))))))
  await waitFor(() => assert.ok(screen.getByText("Couldn’t load settings.")))
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => assert.ok(screen.getByRole('heading', { name: 'Overview' })))
  assert.ok(screen.getByRole('heading', { name: 'Capabilities' }))
})

test('training progress renders truthful zero-step state and invalidates polling on unmount', async () => {
  const { default: TrainingProgress } = await server.ssrLoadModule('/src/components/dataset/TrainingProgress.jsx')
  const calls = []
  globalThis.fetch = async (url) => {
    calls.push(String(url))
    return new Response(JSON.stringify({
      log_exists: true, step: 0, total: 1000, loss: 1.25, samples: [], masks_skipped: true,
    }), { status: 200, headers: { 'content-type': 'application/json' } })
  }
  const mounted = render(React.createElement(TrainingProgress, {
    datasetId: 8, base: 'official', trainType: 'zimage',
  }))
  const progress = await screen.findByRole('progressbar', { name: 'Training progress' })
  assert.equal(progress.getAttribute('aria-valuenow'), '0')
  assert.match(screen.getByText(/0 \/ 1000 steps/).textContent, /0%/)
  assert.ok(screen.getByText((_, element) => element.tagName === 'P'
    && element.textContent.includes('Training UNMASKED')))
  assert.ok(calls[0].includes('base_model=official') && calls[0].includes('train_type=zimage'))
  mounted.unmount()
})

test('actual TrainingPanel degrades truthfully when training initialization is unavailable', async () => {
  const { MemoryRouter } = await server.ssrLoadModule('react-router-dom')
  const { CapabilitiesProvider } = await server.ssrLoadModule('/src/context/CapabilitiesContext.jsx')
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { ConfirmDialogProvider } = await server.ssrLoadModule('/src/components/common/ConfirmDialog.jsx')
  const { default: TrainingPanel } = await server.ssrLoadModule('/src/components/dataset/TrainingPanel.jsx')
  globalThis.fetch = async () => new Response(JSON.stringify({
    training_visible: false, cloud_training: false, engines: {}, comfyui: { models: {} },
  }), { status: 200, headers: { 'content-type': 'application/json' } })
  const counts = []
  render(React.createElement(MemoryRouter, null,
    React.createElement(CapabilitiesProvider, null,
      React.createElement(ToastProvider, null,
        React.createElement(ConfirmDialogProvider, null,
          React.createElement(TrainingPanel, {
            ds: { currentId: 4 }, keptCount: 20, kind: 'character',
            onCheckpointsChange: (count) => counts.push(count),
          }))))))
  assert.ok(await screen.findByText(/Training needs ai-toolkit/))
  await waitFor(() => assert.ok(counts.includes(0)))
  assert.equal(screen.queryByRole('button', { name: /Train/ }), null)
})

test('training monitoring publishes readiness, queue changes, and stops after unmount', async () => {
  const { useTrainingMonitoring } = await server.ssrLoadModule('/src/hooks/useTrainingMonitoring.js')
  const navigation = []
  let statusCalls = 0
  globalThis.fetch = async (url) => {
    assert.equal(String(url), '/api/dataset/train/status')
    statusCalls += 1
    return new Response(JSON.stringify({
      available: true, installed: true, in_progress: false,
      queue: statusCalls === 1 ? [{ dataset_id: 7 }] : [], current: null,
    }), { status: 200, headers: { 'content-type': 'application/json' } })
  }
  function Harness() {
    const monitor = useTrainingMonitoring({
      trainingVisible: true, cloudTraining: false,
      onNavigationStateChange: (state) => navigation.push(state),
    })
    return React.createElement('button', { onClick: monitor.refreshStatus },
      monitor.statusLoaded ? `queue:${monitor.status.queue.length}` : 'loading')
  }
  const mounted = render(React.createElement(Harness))
  assert.ok(await screen.findByRole('button', { name: 'queue:1' }))
  await waitFor(() => assert.ok(navigation.some((state) => state.ready && state.queueCount === 1)))
  fireEvent.click(screen.getByRole('button', { name: 'queue:1' }))
  assert.ok(await screen.findByRole('button', { name: 'queue:0' }))
  await waitFor(() => assert.ok(navigation.some((state) => state.ready && state.queueCount === 0)))
  mounted.unmount()
  const callsAtUnmount = statusCalls
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal(statusCalls, callsAtUnmount)
})

test('actual TrainingPanel reaches local, queued, scheduled, and cloud launch boundaries', async () => {
  const { MemoryRouter } = await server.ssrLoadModule('react-router-dom')
  const { CapabilitiesProvider } = await server.ssrLoadModule('/src/context/CapabilitiesContext.jsx')
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { ConfirmDialogProvider } = await server.ssrLoadModule('/src/components/common/ConfirmDialog.jsx')
  const { default: TrainingPanel } = await server.ssrLoadModule('/src/components/dataset/TrainingPanel.jsx')
  const requests = []
  const trainCalls = []
  let running = false
  let cloudEnabled = false
  const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  })
  globalThis.fetch = async (input, options = {}) => {
    const url = String(input)
    const method = options.method || 'GET'
    requests.push({ url, method, body: options.body ? JSON.parse(options.body) : null })
    if (url.startsWith('/api/capabilities')) return jsonResponse({
      configured: true, training_visible: true, cloud_training: cloudEnabled,
      masks: true, engines: {}, comfyui: { reachable: true, models: {} },
    })
    if (url === '/api/dataset/train/status') return jsonResponse({
      available: true, installed: true, in_progress: running,
      queue: [], current: running ? { dataset_id: 99, name: 'Other dataset' } : null,
    })
    if (url === '/api/dataset/train/cloud/status') return jsonResponse({
      configured: true, limit: 2, actives: [], active: null, total_price_per_hour: 0, last: null,
    })
    if (url.includes('/train/cloud/offers?')) return jsonResponse({
      family: 'zimage', steps: 2400, max_price_per_hour: 2, max_runtime_minutes: 480,
      tiers: [{ gpu_name: 'RTX 4090', gpu_ram_gb: 24, dph_total: 0.5, est_minutes: 30, est_cost: 0.25 }],
    })
    if (url.includes('/train/preflight?')) return jsonResponse({ floor: 1, recommended: 20, blockers: [], warnings: [] })
    if (url === '/api/train/presets') return jsonResponse({ presets: [] })
    if (url.includes('/train/feedback?')) return jsonResponse({ registered: false })
    if (url.endsWith('/train/enqueue') || url.endsWith('/train/schedule') || url.endsWith('/train/cloud')) {
      return jsonResponse({ ok: true })
    }
    throw new Error(`unexpected TrainingPanel request: ${method} ${url}`)
  }
  const ds = {
    currentId: 7, data: {},
    trainBaseInfo: async () => ({
      base: '', variant: 'turbo', train_type: 'zimage', comfyui_configured: true,
      bases: [{ value: '', label: 'Official — Z-Image-Turbo' }],
      bases_by_type: { zimage: [{ value: '', label: 'Official — Z-Image-Turbo' }] },
      train_settings: {},
    }),
    listCheckpoints: async () => ({ checkpoints: [], imported: [], cloud_checkpoints: [], recommended_steps_info: null }),
    train: async (options) => { trainCalls.push(options); return { ok: true } },
    setTrainSettings: async () => ({}),
  }
  const mountPanel = async () => {
    const mounted = render(React.createElement(MemoryRouter, null,
      React.createElement(CapabilitiesProvider, null,
        React.createElement(ToastProvider, null,
          React.createElement(ConfirmDialogProvider, null,
            React.createElement(TrainingPanel, { ds, keptCount: 20, kind: 'character' }))))))
    await screen.findByRole('combobox', { name: 'Type of LoRA to train' })
    await waitFor(() => assert.ok(requests.some((request) => request.url.includes('/train/preflight?'))))
    return mounted
  }
  const user = userEvent.setup({ document })

  let mounted = await mountPanel()
  const localButton = screen.getByRole('button', { name: /Train the LoRA/ })
  await waitFor(() => assert.equal(localButton.disabled, false, localButton.title))
  await user.click(localButton)
  await waitFor(() => assert.equal(trainCalls.length, 1))
  assert.equal(trainCalls[0].trainType, 'zimage')
  mounted.unmount()

  running = true
  mounted = await mountPanel()
  const queueButton = await screen.findByRole('button', { name: /Add to queue/ })
  await waitFor(() => assert.equal(queueButton.disabled, false, queueButton.title))
  await user.click(queueButton)
  await waitFor(() => assert.ok(requests.some((request) => request.url.endsWith('/train/enqueue'))))
  mounted.unmount()

  running = false
  mounted = await mountPanel()
  await user.click(screen.getByText('⚙️ Advanced options'))
  await user.click(await screen.findByRole('button', { name: '⏰ Schedule' }))
  const scheduledAt = screen.getByLabelText('Scheduled training date and time')
  fireEvent.change(scheduledAt, { target: { value: '2026-08-01T12:30' } })
  await user.click(screen.getByRole('button', { name: 'Schedule' }))
  await waitFor(() => assert.ok(requests.some((request) => request.url.endsWith('/train/schedule')
    && request.body.at === '2026-08-01T12:30')))
  mounted.unmount()

  cloudEnabled = true
  mounted = await mountPanel()
  const preflightsBeforeCloud = requests.filter((request) => request.url.includes('/train/preflight?')).length
  const cloudButton = screen.getByRole('button', { name: /Train in cloud/ })
  await waitFor(() => assert.equal(cloudButton.disabled, false, cloudButton.title))
  await user.click(cloudButton)
  await waitFor(() => assert.equal(
    requests.filter((request) => request.url.includes('/train/preflight?')).length,
    preflightsBeforeCloud + 1))
  await user.click(await screen.findByRole('button', { name: /Rent & train/ }))
  await waitFor(() => assert.ok(requests.some((request) => request.url.endsWith('/train/cloud')
    && request.body.gpu_name === 'RTX 4090')))
  assert.equal(requests.filter((request) => request.url.includes('/train/preflight?')).length,
    preflightsBeforeCloud + 1, 'GPU selection must not repeat the launch preflight')
  mounted.unmount()
})

test('resume training dialog exposes fresh, resume, cancel, and keyboard outcomes', async () => {
  const { default: ResumeTrainingDialog } = await server.ssrLoadModule(
    '/src/components/dataset/ResumeTrainingDialog.jsx')
  const outcomes = []
  const mounted = render(React.createElement(ResumeTrainingDialog, {
    checkpoint: { latest: 750, final: false }, onResolve: (value) => outcomes.push(value),
  }))
  assert.equal(screen.getByRole('dialog').getAttribute('aria-modal'), 'true')
  assert.ok(screen.getByRole('heading', { name: /stopped · step 750/ }))
  fireEvent.click(screen.getByRole('button', { name: /Start fresh/ }))
  assert.deepEqual(outcomes, ['fresh'])
  mounted.rerender(React.createElement(ResumeTrainingDialog, {
    checkpoint: { latest: 1000, final: true }, onResolve: (value) => outcomes.push(value),
  }))
  fireEvent.click(screen.getByRole('button', { name: /Continue from step 1000/ }))
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  assert.deepEqual(outcomes, ['fresh', 'resume', null, null])
})

test('server restart waits for a successful settings save and aborts after save failure', async () => {
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { default: ServerSection } = await server.ssrLoadModule(
    '/src/components/settings/ServerSection.jsx')
  const requests = []
  globalThis.fetch = async (url) => {
    requests.push(String(url))
    return new Response(JSON.stringify({ error: 'restart unavailable in test' }), {
      status: 503, headers: { 'content-type': 'application/json' },
    })
  }
  let finishSave
  let saveResult = false
  const handleSave = () => new Promise((resolve) => { finishSave = () => resolve(saveResult) })
  const props = {
    config: { server: { host: '0.0.0.0', port: 9000, require_token: false } },
    runtime: { host: '127.0.0.1', port: 5000, lan_ip: null, tailscale_ip: null },
    setField: () => {}, handleSave,
  }
  const user = userEvent.setup({ document })
  render(React.createElement(ToastProvider, null, React.createElement(ServerSection, props)))
  const restart = screen.getByRole('button', { name: 'Save & restart to apply' })
  await user.click(restart)
  assert.equal(screen.getByRole('button', { name: '↻ Restarting…' }).disabled, true)
  assert.deepEqual(requests, [], 'restart must not race the settings write')
  await testing.act(async () => { finishSave(); await Promise.resolve() })
  assert.deepEqual(requests, [], 'failed save must abort restart')
  saveResult = true
  await user.click(screen.getByRole('button', { name: 'Save & restart to apply' }))
  assert.deepEqual(requests, [])
  await testing.act(async () => { finishSave(); await Promise.resolve() })
  await waitFor(() => assert.equal(requests.length, 1))
  assert.ok(requests[0].endsWith('/api/settings/restart'))
})

test('preflight modal locks resolution actions and restores failure for retry', async () => {
  const { default: PreflightModal } = await server.ssrLoadModule('/src/components/dataset/PreflightModal.jsx')
  let finishReject
  const outcomes = []
  const ds = {
    setStatus: () => new Promise((resolve) => { finishReject = resolve }),
    setCaption: async () => false,
  }
  render(React.createElement(PreflightModal, {
    datasetId: 2, ds, onResolve: (value) => outcomes.push(value),
    report: { warnings: ['Near duplicate'], dup_pairs: [{
      a: { id: 1, filename: 'a.png' }, b: { id: 2, filename: 'b.png' },
    }] },
  }))
  const reject = screen.getByRole('button', { name: /Reject file a.png/ })
  fireEvent.click(reject)
  assert.equal(screen.getByRole('button', { name: 'Saving fixes…' }).disabled, true)
  fireEvent.keyDown(window, { key: 'Escape' })
  assert.deepEqual(outcomes, [])
  await testing.act(async () => { finishReject(false); await Promise.resolve() })
  assert.ok(screen.getByRole('alert'))
  assert.equal(screen.getByRole('button', { name: /Reject file a.png/ }).disabled, false)
  fireEvent.keyDown(window, { key: 'Escape' })
  assert.deepEqual(outcomes, [false])
})

test('installer reattaches to a durable terminal result and notifies once', async () => {
  const { ToastProvider } = await server.ssrLoadModule('/src/components/common/Toast.jsx')
  const { default: InstallRunner } = await server.ssrLoadModule('/src/components/setup/InstallRunner.jsx')
  let done = 0
  const methods = []
  globalThis.fetch = async (_url, options = {}) => {
    methods.push(options.method || 'GET')
    return new Response(JSON.stringify({
    state: 'success', returncode: 0, log: ['complete'], manual_command: 'python -m pip install extras',
    }), { status: 200, headers: { 'content-type': 'application/json' } })
  }
  render(React.createElement(ToastProvider, null, React.createElement(InstallRunner, {
    action: 'quality', buttonLabel: 'Install quality tools', onDone: () => { done += 1 },
  })))
  await waitFor(() => assert.equal(done, 1))
  const reinstall = screen.getByRole('button', { name: 'Install quality tools' })
  assert.equal(reinstall.disabled, false)
  await userEvent.setup({ document }).click(reinstall)
  await waitFor(() => assert.equal(done, 2))
  assert.ok(methods.includes('POST'))
})

test('Dataset lightbox restores async actions and closes from the keyboard', async () => {
  const { default: DatasetLightbox } = await server.ssrLoadModule(
    '/src/components/dataset/DatasetLightbox.jsx')
  const calls = []
  let finishImprove
  const improve = () => new Promise((resolve) => { finishImprove = resolve })
  const user = userEvent.setup({ document })
  render(React.createElement(DatasetLightbox, {
    img: { id: 9, filename: 'face.png', variation_label: 'portrait', source: 'import' },
    datasetId: 3, kleinAvailable: true, onImprove: improve,
    onClose: () => calls.push('close'), onCrop: () => calls.push('crop'),
  }))
  assert.equal(screen.getByRole('dialog').getAttribute('aria-modal'), 'true')
  assert.equal(document.activeElement, screen.getByRole('button', { name: 'Close inspection' }))
  const action = screen.getByRole('button', { name: /Reconstruct & compare/ })
  await user.click(action)
  assert.equal(action.disabled, true)
  await testing.act(async () => { finishImprove(false); await Promise.resolve() })
  assert.equal(screen.getByRole('button', { name: /Reconstruct & compare/ }).disabled, false)
  fireEvent.keyDown(window, { key: 'Escape' })
  assert.deepEqual(calls, ['close'])
})

test('small-image rescue prevents re-entry and restores choices after failure', async () => {
  const { default: SmallImageRescueReview } = await server.ssrLoadModule(
    '/src/components/dataset/SmallImageRescueReview.jsx')
  let finishChoice
  let calls = 0
  const onResolve = () => {
    calls += 1
    return new Promise((resolve) => { finishChoice = resolve })
  }
  const images = [
    { id: 1, filename: 'small.jpg', status: 'pending', derivation_kind: 'small_image_source' },
    { id: 2, parent_image_id: 1, filename: 'klein.png', status: 'pending', derivation_kind: 'klein_small_image' },
  ]
  const user = userEvent.setup({ document })
  render(React.createElement(SmallImageRescueReview, {
    images, datasetId: 4, onResolve,
  }))
  const choose = screen.getByRole('button', { name: 'Use Klein' })
  await user.click(choose)
  await user.click(choose)
  assert.equal(calls, 1)
  assert.equal(choose.closest('article').getAttribute('aria-busy'), 'true')
  await testing.act(async () => { finishChoice(false); await Promise.resolve() })
  assert.equal(screen.getByRole('button', { name: 'Use Klein' }).disabled, false)
})

test('crop modal is single-flight and recovers after rejected persistence', async () => {
  const { default: CropModal } = await server.ssrLoadModule(
    '/src/components/dataset/CropModal.jsx')
  let finishCrop
  let calls = 0
  const onConfirm = () => {
    calls += 1
    return new Promise((resolve) => { finishCrop = resolve })
  }
  const user = userEvent.setup({ document })
  render(React.createElement(CropModal, {
    imageUrl: '/image.png', onCancel: () => {}, onConfirm,
  }))
  const image = screen.getByRole('img')
  Object.defineProperties(image, {
    naturalWidth: { configurable: true, value: 800 },
    naturalHeight: { configurable: true, value: 600 },
  })
  fireEvent.load(image)
  const crop = await screen.findByRole('button', { name: 'Crop' })
  await user.click(crop)
  await user.click(crop)
  assert.equal(calls, 1)
  assert.ok(screen.getByRole('button', { name: 'Cropping…' }).disabled)
  await testing.act(async () => { finishCrop(false); await Promise.resolve() })
  assert.equal(screen.getByRole('button', { name: 'Crop' }).disabled, false)
})

test('shared model and resolution controls reconcile state and expose keyboard semantics', async () => {
  const { CapabilitiesProvider } = await server.ssrLoadModule(
    '/src/context/CapabilitiesContext.jsx')
  const { default: Flux2KleinModelPicker } = await server.ssrLoadModule(
    '/src/components/shared/Flux2KleinModelPicker.jsx')
  const { default: ResolutionSelector } = await server.ssrLoadModule(
    '/src/components/shared/ResolutionSelector.jsx')
  localStorage.setItem('editPage_flux2KleinModel_v1', 'missing.safetensors')
  globalThis.fetch = async () => new Response(JSON.stringify({
    comfyui: { models: { klein: ['first.safetensors', 'second.safetensors'] } },
    resolution_metadata: {
      tiers: [{ value: 'fast', label: 'Fast' }, { value: 'hq', label: 'HQ' }],
      dimensions: { square: { fast: [512, 512], hq: [1024, 1024] } },
    },
  }), { status: 200, headers: { 'content-type': 'application/json' } })
  const models = []
  const tiers = []
  const onModel = (value) => models.push(value)
  const onTier = (value) => tiers.push(value)
  render(React.createElement(CapabilitiesProvider, null,
    React.createElement(Flux2KleinModelPicker, { onChange: onModel }),
    React.createElement(ResolutionSelector, {
      value: 'fast', aspectRatio: 'square', onChange: onTier,
    })))
  const select = await screen.findByRole('combobox', { name: 'Base model' })
  await waitFor(() => assert.equal(select.value, 'first.safetensors'))
  assert.equal(localStorage.getItem('editPage_flux2KleinModel_v1'), 'first.safetensors')
  const fast = screen.getByRole('radio', { name: /Fast/ })
  fast.focus()
  fireEvent.keyDown(fast.closest('[role="radiogroup"]'), { key: 'ArrowRight' })
  assert.deepEqual(tiers, ['hq'])
  assert.ok(models.includes('first.safetensors'))
})

test('Z-Image LoRA controls migrate persistence, lock strength, and report enabled stack', async () => {
  const { default: ZImageLoraConfig } = await server.ssrLoadModule(
    '/src/components/shared/ZImageLoraConfig.jsx')
  localStorage.setItem('matrix-loras', JSON.stringify({
    'hero.safetensors': { enabled: true, strength: '99', locked: true },
  }))
  const emitted = []
  const onChange = (value) => emitted.push(value)
  render(React.createElement(ZImageLoraConfig, {
    storageKey: 'matrix-loras', onChange,
    loras: [{ filename: 'hero.safetensors', displayName: 'Hero', triggerWord: 'hero' }],
  }))
  const slider = screen.getByRole('slider', { name: 'Strength of Hero' })
  await waitFor(() => assert.equal(slider.value, '2'))
  assert.equal(slider.disabled, true)
  assert.equal(screen.getByRole('button', { name: 'Unlock strength for Hero' })
    .getAttribute('aria-pressed'), 'true')
  fireEvent.change(slider, { target: { value: '1.25' } })
  assert.equal(slider.value, '2')
  assert.deepEqual(emitted.at(-1), [{ filename: 'hero.safetensors', strength: 2 }])
})

test('dataset bulk actions retain the selection after partial failure and prune vanished rows', async () => {
  const { ConfirmDialogProvider } = await server.ssrLoadModule(
    '/src/components/common/ConfirmDialog.jsx')
  const { default: DatasetGrid } = await server.ssrLoadModule(
    '/src/components/dataset/DatasetGrid.jsx')
  const images = [
    { id: 1, filename: 'one.png', status: 'pending', source: 'import' },
    { id: 2, filename: 'two.png', status: 'pending', source: 'import' },
  ]
  const batches = []
  const props = {
    images, datasetId: 7, busy: false, nonces: {}, faceThresholds: {},
    onBatch: async (ids, action) => { batches.push([ids, action]); return 1 },
    onStatus: () => {}, onCaption: () => {}, onCrop: () => {},
    onDelete: () => {}, onRegenerate: () => {}, onView: () => {},
  }
  const mounted = render(React.createElement(ConfirmDialogProvider, null,
    React.createElement(DatasetGrid, props)))
  const user = userEvent.setup({ document })
  await user.click(screen.getByRole('button', { name: 'select all (2)' }))
  await user.click(screen.getByRole('toolbar', { name: 'Bulk actions on the selection' })
    .querySelector('button'))
  await waitFor(() => assert.match(screen.getByRole('alert').textContent, /Only 1 of 2/))
  assert.deepEqual(batches, [[[1, 2], 'keep']])
  assert.ok(screen.getByRole('toolbar', { name: 'Bulk actions on the selection' }))
  mounted.rerender(React.createElement(ConfirmDialogProvider, null,
    React.createElement(DatasetGrid, { ...props, images: [images[0]] })))
  await waitFor(() => assert.match(screen.getByText('1 selected').textContent, /1 selected/))
})

test('publish modal preserves typed repository data and recovers from a rejected launch', async () => {
  const { default: PublishHfModal } = await server.ssrLoadModule(
    '/src/components/dataset/PublishHfModal.jsx')
  let resolveWhoami
  let resolvePost
  let postCount = 0
  globalThis.fetch = async (url, options = {}) => {
    if (String(url).endsWith('/whoami')) {
      return new Promise((resolve) => { resolveWhoami = () => resolve(new Response(JSON.stringify({
        ok: true, username: 'server', default_repo_id: 'server/default',
      }), { status: 200, headers: { 'content-type': 'application/json' } })) })
    }
    if (String(url).endsWith('/status')) {
      return new Response(JSON.stringify({ state: 'idle' }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    if (options.method === 'POST') {
      postCount += 1
      return new Promise((resolve) => { resolvePost = () => resolve(new Response(JSON.stringify({
        ok: false, error: 'Token cannot publish',
      }), { status: 200, headers: { 'content-type': 'application/json' } })) })
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }
  const user = userEvent.setup({ document })
  render(React.createElement(PublishHfModal, { datasetId: 8, onClose: () => {} }))
  const repository = screen.getByRole('textbox', { name: 'Repository' })
  await user.type(repository, 'me/typed')
  await testing.act(async () => { resolveWhoami(); await Promise.resolve() })
  await waitFor(() => assert.equal(repository.value, 'me/typed'))
  await user.click(screen.getByRole('checkbox', { name: /I have the right to share/ }))
  const publish = screen.getByRole('button', { name: 'Publish' })
  await user.click(publish)
  await user.click(screen.getByRole('button', { name: /Publishing/ }))
  await testing.act(async () => { resolvePost(); await Promise.resolve() })
  await waitFor(() => assert.match(screen.getByText('Token cannot publish').textContent, /cannot publish/))
  assert.equal(postCount, 1)
  assert.equal(screen.getByRole('button', { name: 'Publish' }).disabled, false)
})

test('watermark editor supports keyboard move, delete, and accessible add mode', async () => {
  const { default: WatermarkRegionEditor } = await server.ssrLoadModule(
    '/src/components/dataset/WatermarkRegionEditor.jsx')
  const commits = []
  const addModes = []
  const props = {
    src: '/watermark.png', alt: 'Watermark candidate', disabled: false,
    regions: [[0.2, 0.2, 0.4, 0.4]], selectedIndex: 0,
    onSelectedIndexChange: () => {}, onCommit: (regions) => commits.push(regions),
    onAddModeChange: (value) => addModes.push(value),
  }
  const mounted = render(React.createElement(WatermarkRegionEditor, props))
  const mover = screen.getByRole('button', { name: 'Select and move watermark zone 1 of 1' })
  fireEvent.keyDown(mover, { key: 'ArrowRight' })
  assert.ok(Math.abs(commits.at(-1)[0][0] - 0.21) < 1e-10)
  assert.ok(Math.abs(commits.at(-1)[0][2] - 0.41) < 1e-10)
  fireEvent.keyDown(mover, { key: 'Delete' })
  assert.deepEqual(commits.at(-1), [])
  mounted.rerender(React.createElement(WatermarkRegionEditor, {
    ...props, regions: [], selectedIndex: null, addMode: true,
  }))
  const add = screen.getByRole('button', { name: 'Drag to add a watermark zone' })
  fireEvent.keyDown(add, { key: 'Enter' })
  assert.deepEqual(commits.at(-1), [[0.35, 0.35, 0.65, 0.65]])
  assert.deepEqual(addModes, [false])
})

test('watermark review blocks duplicate actions, recovers from failure, and cleans up shortcuts', async () => {
  const { default: WatermarkReviewLightbox } = await server.ssrLoadModule(
    '/src/components/dataset/WatermarkReviewLightbox.jsx')
  let resolveDismiss
  let dismissCalls = 0
  const closes = []
  const queue = [{
    id: 20, filename: 'flagged.png', source: 'import', variation_label: 'portrait',
    watermark_bbox: [0.1, 0.1, 0.3, 0.3], watermark_route: 'crop',
  }]
  const mounted = render(React.createElement(WatermarkReviewLightbox, {
    datasetId: 9, queue, caps: {}, onSaveRegions: async () => ({ ok: true }),
    onClean: async () => ({ ok: true }), onReject: async () => true,
    onDismiss: () => {
      dismissCalls += 1
      return new Promise((resolve) => { resolveDismiss = resolve })
    },
    onClose: (recap) => closes.push(recap),
  }))
  const user = userEvent.setup({ document })
  const dismiss = screen.getByRole('button', { name: /Not a watermark/ })
  await user.click(dismiss)
  await user.click(dismiss)
  assert.equal(dismissCalls, 1)
  assert.equal(screen.getByRole('button', { name: 'Close review' }).disabled, true)
  await testing.act(async () => { resolveDismiss({ ok: false, error: 'Dismiss denied' }); await Promise.resolve() })
  await waitFor(() => assert.match(screen.getByText('Dismiss denied').textContent, /denied/))
  assert.equal(screen.getByRole('button', { name: 'Close review' }).disabled, false)
  fireEvent.keyDown(window, { key: 'Escape' })
  assert.deepEqual(closes, [''])
  mounted.unmount()
  fireEvent.keyDown(window, { key: 'Escape' })
  assert.deepEqual(closes, [''], 'unmount must remove the global shortcut handler')
})

test('watermark review contains failed region saves until an explicit retry succeeds', async () => {
  const { default: WatermarkReviewLightbox } = await server.ssrLoadModule(
    '/src/components/dataset/WatermarkReviewLightbox.jsx')
  const saves = []
  const closes = []
  const queue = [{
    id: 21, filename: 'manual.png', source: 'generated', variation_label: 'close-up',
    watermark_bbox: [0.1, 0.1, 0.3, 0.3],
    watermark_regions: [[0.2, 0.2, 0.4, 0.4]],
    effective_watermark_regions: [[0.2, 0.2, 0.4, 0.4]], watermark_route: 'lama',
  }]
  const onSaveRegions = async (id, regions) => {
    saves.push([id, regions])
    return saves.length === 1
      ? { ok: false, error: 'Region save denied' }
      : { ok: true, watermark_regions: regions, effective_watermark_regions: regions }
  }
  const user = userEvent.setup({ document })
  render(React.createElement(WatermarkReviewLightbox, {
    datasetId: 9, queue, caps: { watermark_inpaint: true }, onSaveRegions,
    onClean: async () => ({ ok: true }), onDismiss: async () => ({ ok: true }),
    onReject: async () => true, onClose: (recap) => closes.push(recap),
  }))
  await user.click(screen.getByRole('button', { name: 'Delete zone' }))
  await waitFor(() => assert.match(screen.getByRole('alert').textContent, /Region save denied/))
  assert.equal(screen.getByRole('button', { name: 'Close review' }).disabled, true)
  fireEvent.keyDown(window, { key: 'Escape' })
  assert.deepEqual(closes, [])
  await user.click(screen.getByRole('button', { name: 'Retry save' }))
  await waitFor(() => assert.match(screen.getByText(/Saved/).textContent, /Saved/))
  assert.deepEqual(saves, [[21, []], [21, []]])
  fireEvent.keyDown(window, { key: 'Escape' })
  assert.deepEqual(closes, [''])
})
