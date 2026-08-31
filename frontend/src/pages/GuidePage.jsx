import { useEffect, useRef } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import Markdown from '../components/common/Markdown'
import { markdownHeadingModel } from '../utils/markdownHeadings'
import DiagnosticReport from '../components/common/DiagnosticReport'
// Vite inlines every chapter as a string at build time (?raw) → the guide
// lives in the bundle, no fetch, nothing extra to ship in the portable build.
// DATASET_GUIDE.md keeps its historical path (linked from GitHub); the other
// chapters live in docs/guide/.
import gettingStarted from '../../../docs/guide/getting-started.md?raw'
import imageProvider from '../../../docs/guide/steps/02-image-provider.md?raw'
import comfyui from '../../../docs/guide/steps/03-comfyui.md?raw'
import localVision from '../../../docs/guide/steps/04-local-vision.md?raw'
import qualityTools from '../../../docs/guide/steps/05-quality-tools.md?raw'
import trainingTools from '../../../docs/guide/steps/06-training-tools.md?raw'
import createDataset from '../../../docs/guide/steps/07-create-dataset.md?raw'
import importPhotos from '../../../docs/guide/steps/08-import-photos.md?raw'
import reviewCorpus from '../../../docs/guide/steps/09-review-corpus.md?raw'
import chooseAnchors from '../../../docs/guide/steps/10-choose-anchors.md?raw'
import planCoverage from '../../../docs/guide/steps/11-plan-coverage.md?raw'
import primaryReference from '../../../docs/guide/steps/12-primary-reference.md?raw'
import generateGaps from '../../../docs/guide/steps/13-generate-gaps.md?raw'
import curateImages from '../../../docs/guide/steps/14-curate-images.md?raw'
import captionImages from '../../../docs/guide/steps/15-caption-images.md?raw'
import scoreImages from '../../../docs/guide/steps/16-score-images.md?raw'
import exportDataset from '../../../docs/guide/steps/17-export-dataset.md?raw'
import trainLora from '../../../docs/guide/steps/18-train-lora.md?raw'
import reviewCheckpoints from '../../../docs/guide/steps/19-review-checkpoints.md?raw'
import testStudio from '../../../docs/guide/steps/20-test-studio.md?raw'
import backUp from '../../../docs/guide/steps/21-back-up.md?raw'
import datasetGuide from '../../../docs/DATASET_GUIDE.md?raw'
import troubleshooting from '../../../docs/guide/troubleshooting.md?raw'
import gettingHelp from '../../../docs/guide/getting-help.md?raw'

/* The guide is a true reading sequence — the mono chapter numbers encode the
   intended order, not decoration. `extra` mounts a live component under the
   markdown (the diagnostic button on the help chapter). */
const step = (id, num, title, description, source) => ({ id, num, title, description, source, group: 'First run' })

export const FIRST_RUN_STEPS = [
  step('getting-started', '01', 'Open the app', 'Install and launch Prep My Avatar, then start or skip the five-page Setup wizard.', gettingStarted),
  step('image-provider', '02', 'Choose an image provider', 'Optionally connect Gemini, Replicate, or OpenAI for remote image generation.', imageProvider),
  step('comfyui', '03', 'Configure ComfyUI', 'Optionally enable local Klein generation and Test Studio.', comfyui),
  step('local-vision', '04', 'Configure local vision', 'Optionally connect Ollama, LM Studio, or llama.cpp for image analysis and captions.', localVision),
  step('quality-tools', '05', 'Install quality tools', 'Optionally add face scoring, person masks, and watermark repair.', qualityTools),
  step('training-tools', '06', 'Configure training', 'Optionally connect ai-toolkit for local LoRA training.', trainingTools),
  step('create-dataset', '07', 'Create a dataset', 'Create a Character, Concept, or Style project with the right target model.', createDataset),
  step('import-photos', '08', 'Import photos', 'Add the real source images that form your complete photo collection.', importPhotos),
  step('review-corpus', '09', 'Review photos', 'Classify, accept, or reject every imported image.', reviewCorpus),
  step('choose-anchors', '10', 'Choose photos for generation', 'Control which accepted photos may be used as references when creating new images.', chooseAnchors),
  step('plan-coverage', '11', 'Check photo variety', 'Check the mix of views and identify genuinely missing kinds of photos.', planCoverage),
  step('primary-reference', '12', 'Set a primary reference', 'Optionally choose the identity image used by local Klein and face-similarity scoring.', primaryReference),
  step('generate-gaps', '13', 'Generate missing views', 'Optionally create candidates for proven coverage gaps.', generateGaps),
  step('curate-images', '14', 'Curate images', 'Keep the useful images, reject the rest, and resolve every comparison.', curateImages),
  step('caption-images', '15', 'Caption images', 'Generate or write accurate captions and remove target leaks.', captionImages),
  step('score-images', '16', 'Score face similarity', 'Optionally use face scores to find Character images that need review.', scoreImages),
  step('export-dataset', '17', 'Export dataset', 'Download standard image and caption pairs for another trainer.', exportDataset),
  step('train-lora', '18', 'Train a LoRA', 'Optionally launch a local or cloud training run.', trainLora),
  step('review-checkpoints', '19', 'Review checkpoints', 'Keep the checkpoints worth comparing and trace each to its run.', reviewCheckpoints),
  step('test-studio', '20', 'Test in Studio', 'Compare checkpoints and strengths with controlled prompts and seeds.', testStudio),
  step('back-up', '21', 'Back up dataset', 'Create and verify a portable dataset backup, then copy training artefacts separately.', backUp),
]
export const REFERENCE_CHAPTERS = [
  { id: 'dataset-guide', num: 'R1', title: 'Building a good dataset', description: 'Understand the reasoning behind image, caption, training, and checkpoint choices.', source: datasetGuide, group: 'Reference' },
  { id: 'troubleshooting', num: 'R2', title: 'Troubleshooting', description: 'Find a symptom, understand the cause, and apply the shortest reliable fix.', source: troubleshooting, group: 'Reference' },
]
export const CHAPTERS = [...FIRST_RUN_STEPS, ...REFERENCE_CHAPTERS]
export const HELP_CHAPTER = { id: 'getting-help', num: 'R3', title: 'Getting help', description: 'Create a useful report and share the details needed to solve a problem.', source: gettingHelp, group: 'Support', extra: 'diagnostic' }
export const ALL_GUIDE_CHAPTERS = [...CHAPTERS, HELP_CHAPTER]
export const GUIDE_DOCUMENT_ROUTES = Object.freeze({
  'getting-started.md': '/guide/getting-started',
  'using-the-app.md': '/guide/getting-started',
  'steps/02-image-provider.md': '/guide/image-provider',
  'steps/03-comfyui.md': '/guide/comfyui',
  'steps/04-local-vision.md': '/guide/local-vision',
  'steps/05-quality-tools.md': '/guide/quality-tools',
  'steps/06-training-tools.md': '/guide/training-tools',
  'steps/07-create-dataset.md': '/guide/create-dataset',
  'steps/08-import-photos.md': '/guide/import-photos',
  'steps/09-review-corpus.md': '/guide/review-corpus',
  'steps/10-choose-anchors.md': '/guide/choose-anchors',
  'steps/11-plan-coverage.md': '/guide/plan-coverage',
  'steps/12-primary-reference.md': '/guide/primary-reference',
  'steps/13-generate-gaps.md': '/guide/generate-gaps',
  'steps/14-curate-images.md': '/guide/curate-images',
  'steps/15-caption-images.md': '/guide/caption-images',
  'steps/16-score-images.md': '/guide/score-images',
  'steps/17-export-dataset.md': '/guide/export-dataset',
  'steps/18-train-lora.md': '/guide/train-lora',
  'steps/19-review-checkpoints.md': '/guide/review-checkpoints',
  'steps/20-test-studio.md': '/guide/test-studio',
  'steps/21-back-up.md': '/guide/back-up',
  '../DATASET_GUIDE.md': '/guide/dataset-guide',
  'troubleshooting.md': '/guide/troubleshooting',
  'getting-help.md': '/help',
})
export const resolveGuideLink = (href) => {
  const route = GUIDE_DOCUMENT_ROUTES[href]
  return route ? `#${route}` : null
}
export const guideHeadingRoute = (chapterId, headingId) => (
  `${chapterId === 'getting-help' ? '/help' : `/guide/${chapterId}`}?heading=${encodeURIComponent(headingId)}`
)
export const focusGuideHeading = (headingId) => {
  const target = document.getElementById(headingId)
  if (!target) return false
  target.tabIndex = -1
  target.focus({ preventScroll: true })
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  target.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
  return true
}
export const keepGuideItemVisible = (nav, item) => {
  if (!nav || !item) return
  const navRect = nav.getBoundingClientRect()
  const itemRect = item.getBoundingClientRect()
  if (itemRect.top < navRect.top) nav.scrollTop -= navRect.top - itemRect.top
  else if (itemRect.bottom > navRect.bottom) nav.scrollTop += itemRect.bottom - navRect.bottom
}

export default function GuidePage({ helpOnly = false }) {
  const { section } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const chapters = helpOnly ? [HELP_CHAPTER] : CHAPTERS
  const requestedSection = section || 'getting-started'
  const idx = helpOnly ? 0 : chapters.findIndex((c) => c.id === requestedSection)
  const validSection = helpOnly || idx >= 0
  const headingRef = useRef(null)
  const desktopNavRef = useRef(null)
  const activeNavItemRef = useRef(null)
  const chapter = validSection ? chapters[idx] : chapters[0]
  const groupChapters = chapters.filter((item) => item.group === chapter.group)
  const groupIndex = groupChapters.findIndex((item) => item.id === chapter.id)
  const prev = groupIndex > 0 ? groupChapters[groupIndex - 1] : null
  const next = groupIndex >= 0 && groupIndex < groupChapters.length - 1
    ? groupChapters[groupIndex + 1] : null
  const headings = markdownHeadingModel(chapter.source)
  const readingMinutes = Math.max(1, Math.ceil(chapter.source.trim().split(/\s+/).length / 210))
  const firstRunIndex = FIRST_RUN_STEPS.findIndex((item) => item.id === chapter.id)
  const jumpToHeading = (event, id) => {
    event.preventDefault()
    const route = guideHeadingRoute(chapter.id, id)
    if (`${location.pathname}${location.search}` === route) {
      focusGuideHeading(id)
      return
    }
    navigate(route, { replace: true })
  }

  // A chapter switch is a new "page" — land the reader at its top, not at the
  // scroll depth of the previous chapter.
  useEffect(() => {
    if (!validSection) return
    const headingId = new URLSearchParams(location.search).get('heading')
    if (!headingId || !focusGuideHeading(headingId)) {
      window.scrollTo(0, 0)
      headingRef.current?.focus()
    }
  }, [chapter.id, location.search, validSection])

  useEffect(() => {
    keepGuideItemVisible(desktopNavRef.current, activeNavItemRef.current)
  }, [chapter.id])

  if (!validSection) return <Navigate to="/guide/getting-started" replace />

  const navItem = (c) => {
    const isActive = c.id === chapter.id
    const base = `relative flex w-full items-baseline gap-2.5 rounded-md px-3 py-2 text-left text-sm ${
      isActive ? 'bg-surface-raised text-content' : 'text-content-muted hover:bg-surface hover:text-content'}`
    return (
      <Link key={c.id} to={`/guide/${c.id}`}
        ref={isActive ? activeNavItemRef : undefined}
        aria-current={isActive ? 'page' : undefined} className={base}>
        {isActive && (
          <span aria-hidden className="absolute bottom-1.5 left-0 top-1.5 w-0.5 rounded bg-gradient-primary" />
        )}
        <span className={`font-mono text-[11px] ${isActive ? 'text-content' : 'text-content-subtle'}`}>{c.num}</span>
        <span className="font-medium">{c.title}</span>
      </Link>
    )
  }

  return (
    <div className={helpOnly
      ? 'mx-auto max-w-5xl xl:grid xl:grid-cols-[minmax(0,1fr)_190px] xl:items-start xl:gap-7'
      : 'lg:grid lg:grid-cols-[210px_minmax(0,1fr)] lg:items-start lg:gap-7 xl:grid-cols-[210px_minmax(0,1fr)_190px]'}>
      {!helpOnly && <aside>
        {/* Mobile: one compact page picker; 23 horizontal chips are not usable on a phone. */}
        <nav aria-label="Guide chapters" className="pb-3 lg:hidden">
          <label htmlFor="guide-page" className="mb-1 block font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle">
            Guide page
          </label>
          <select id="guide-page" aria-label="Guide page" value={chapter.id}
            onChange={(event) => navigate(`/guide/${event.target.value}`)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-content">
            <optgroup label="First run">
              {FIRST_RUN_STEPS.map((item) => <option key={item.id} value={item.id}>{item.num} — {item.title}</option>)}
            </optgroup>
            <optgroup label="Reference">
              {REFERENCE_CHAPTERS.map((item) => <option key={item.id} value={item.id}>{item.num} — {item.title}</option>)}
            </optgroup>
          </select>
        </nav>
        {/* Desktop: sticky numbered chapter rail */}
        <nav ref={desktopNavRef} aria-label="Guide chapters" className="hidden lg:sticky lg:top-20 lg:block lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-1">
          <p className="px-3 pb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle">First run</p>
          <div className="flex flex-col gap-0.5">{FIRST_RUN_STEPS.map(navItem)}</div>
          <p className="mt-4 px-3 pb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle">Reference</p>
          <div className="flex flex-col gap-0.5">{REFERENCE_CHAPTERS.map(navItem)}</div>
        </nav>
      </aside>}

      <section className={`min-w-0 max-w-4xl pb-10 ${helpOnly ? 'mx-auto' : 'mt-2 lg:mt-0'}`}>
        <header className="relative mb-4 overflow-hidden rounded-2xl border border-border bg-surface px-5 py-5 sm:px-6 sm:py-6">
          <div aria-hidden className="absolute -right-16 -top-20 h-52 w-52 rounded-full bg-indigo-500/10 blur-3xl" />
          <div className="relative">
            <div className="mb-3 flex flex-wrap items-center gap-2 font-mono text-[0.6875rem] uppercase tracking-[0.14em] text-content-subtle">
              <span className="rounded-md border border-indigo-400/30 bg-indigo-500/10 px-2 py-1 text-indigo-300">
                {helpOnly ? 'Support' : firstRunIndex >= 0 ? `Step ${chapter.num}` : 'Reference'}
              </span>
              <span>{readingMinutes} min read</span>
              {firstRunIndex >= 0 && <><span aria-hidden>·</span><span>{firstRunIndex + 1} of {FIRST_RUN_STEPS.length}</span></>}
            </div>
            <h1 ref={headingRef} tabIndex={-1} className="m-0 max-w-2xl text-2xl font-bold tracking-tight text-content focus:outline-none sm:text-3xl">{chapter.title}</h1>
            <p className="mb-0 mt-2 max-w-2xl text-sm leading-relaxed text-content-muted sm:text-base">{chapter.description}</p>
          </div>
        </header>

        {headings.length > 0 && (
          <nav aria-label="On this page" className="mb-4 rounded-xl border border-border bg-surface p-3 xl:hidden">
            <p className="m-0 mb-2 font-mono text-[0.625rem] uppercase tracking-[0.16em] text-content-subtle">On this page</p>
            <div className="flex gap-2 overflow-x-auto pb-0.5">
              {headings.map((item) => (
                <a key={item.id} href={`#${guideHeadingRoute(chapter.id, item.id)}`} onClick={(event) => jumpToHeading(event, item.id)}
                  className="shrink-0 rounded-full border border-border bg-transparent px-2.5 py-1 text-xs text-content-muted hover:border-border-strong hover:text-content">{item.title}</a>
              ))}
            </div>
          </nav>
        )}

        <Markdown source={chapter.source} variant="guide" resolveLink={resolveGuideLink} />

        {chapter.extra === 'diagnostic' && (
          <div className="mt-6">
            <DiagnosticReport />
          </div>
        )}

        {!helpOnly && <div className="mt-6 grid grid-cols-2 gap-3 border-t border-border pt-4">
          {prev ? (
            <Link to={`/guide/${prev.id}`} className="group flex min-w-0 items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 no-underline hover:bg-surface-raised">
              <span aria-hidden className="text-content-subtle">←</span>
              <span className="min-w-0"><span className="block font-mono text-[0.625rem] uppercase tracking-wider text-content-subtle">Previous</span><span className="block truncate text-sm font-medium text-content-muted group-hover:text-content">{prev.title}</span></span>
            </Link>
          ) : <span />}
          {next ? (
            <Link to={`/guide/${next.id}`} className="group flex min-w-0 items-center justify-end gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 text-right no-underline hover:bg-surface-raised">
              <span className="min-w-0"><span className="block font-mono text-[0.625rem] uppercase tracking-wider text-content-subtle">Next</span><span className="block truncate text-sm font-medium text-content-muted group-hover:text-content">{next.title}</span></span>
              <span aria-hidden className="text-content-subtle">→</span>
            </Link>
          ) : <span />}
        </div>}
      </section>

      <aside className="hidden xl:block">
        <nav aria-label="On this page" className="sticky top-20 border-l border-border pl-4">
          <p className="m-0 mb-2 font-mono text-[0.625rem] uppercase tracking-[0.16em] text-content-subtle">On this page</p>
          <div className="flex flex-col gap-0.5">
            {headings.map((item) => (
              <a key={item.id} href={`#${guideHeadingRoute(chapter.id, item.id)}`} onClick={(event) => jumpToHeading(event, item.id)}
                className="rounded-md bg-transparent px-2 py-1.5 text-left text-xs leading-snug text-content-subtle hover:bg-surface hover:text-content">{item.title}</a>
            ))}
          </div>
        </nav>
      </aside>
    </div>
  )
}
