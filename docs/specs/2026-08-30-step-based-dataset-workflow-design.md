# Step-based dataset workflow

## Objective

Replace the dataset workspace's broad, multi-purpose sections with a guided
workflow in which one route, page title, and primary action represent one user
step. The application workflow must use the same order and language as the
first-run guide so a new user never has to translate documentation steps into
different in-app sections.

The change is a frontend navigation and presentation refactor. Existing
dataset records, API contracts, background jobs, saved progress, and generated
artifacts remain compatible.

## Workflow contract

The canonical character-dataset sequence is:

1. Import photos
2. Review corpus
3. Choose anchors
4. Review coverage
5. Set primary reference (optional)
6. Generate missing views (optional)
7. Curate images
8. Caption images
9. Score face similarity (optional)
10. Export dataset
11. Train a LoRA (optional)
12. Review checkpoints (optional)
13. Test in Studio (optional)
14. Back up dataset

Concept and Style datasets use the same sequence but omit steps that do not
apply to them: anchors, coverage, primary reference, generation, and face
similarity. Capability-dependent steps remain visible and explain what must be
configured; they do not disappear without explanation.

Every step has:

- a stable slug and route at `/datasets/:datasetId/:step`;
- one `h1` describing the current task;
- a short explanation of why the task matters and how completion is detected;
- only the controls needed for that task;
- Back and Continue controls;
- an explicit Skip action when the step is optional;
- completed, current, optional, unavailable, and upcoming states in the step
  navigator using text or symbols as well as colour.

Opening `/datasets/:datasetId` resumes at the first incomplete required step.
Unknown or inapplicable step slugs normalize to that resumable step. Historical
`/datasets?section=...&panel=...` links map to the closest canonical step.

## Tech stack and commands

- React 18 and React Router 6 in `frontend/src`.
- Tailwind CSS using the existing semantic colour and spacing tokens.
- Node's test runner for unit and source-contract tests.
- Playwright for critical browser flows.

```bash
cd frontend
pnpm run test:navigation
pnpm run test
pnpm run lint
pnpm run typecheck
pnpm run build
pnpm run check:bundle
pnpm run e2e
```

## Project structure

- `frontend/src/components/dataset/datasetWorkflow.js` owns stable step
  definitions, applicability, route normalization, and neighboring-step logic.
- `frontend/src/components/dataset/DatasetWorkflowNav.jsx` renders desktop and
  mobile progress navigation plus Back/Continue/Skip actions.
- `frontend/src/components/dataset/DatasetWorkspace.jsx` remains the data and
  background-job orchestrator while rendering only the active step's visible
  content.
- `frontend/src/components/dataset/CorpusWorkbench.jsx` exposes focused review,
  anchor, and coverage modes rather than displaying all three concerns at once.
- `frontend/src/pages/DatasetPage.jsx` binds route parameters to the persisted
  dataset selection and compatibility redirects.
- `docs/guide/steps/07-create-dataset.md` through
  `docs/guide/steps/21-back-up.md` use the same labels and navigation as the app.

## Code style

Workflow decisions are pure and data-driven. Components consume the resulting
step model rather than repeating route conditionals.

```js
const step = resolveDatasetStep({ requestedSlug, kind, completed });
const next = adjacentDatasetStep(step.slug, 1, { kind });
```

Stable slugs are lowercase kebab-case. Presentation components receive explicit
props and do not fetch data. Existing API mutation methods stay in `useDataset`.

## Testing strategy

- Unit tests prove step ordering, kind-specific applicability, optional status,
  resume behavior, legacy-link mapping, and previous/next navigation.
- Component/source-contract tests prove one visible step surface at a time,
  correct headings and accessible current-step semantics.
- Playwright covers opening a dataset, direct/reloaded step URLs, Back,
  Continue, Skip, mobile navigation, and legacy links.
- The complete frontend gate proves lint, type coverage, tests, build, and bundle
  budgets remain clean.

## Boundaries

### Always

- Preserve running dataset, generation, captioning, and training state across
  step navigation.
- Preserve unrelated query parameters where compatibility requires them.
- Keep step labels identical in the app and first-run guide.
- Support keyboard navigation and 320, 768, 1024, and 1440 px layouts.
- Regenerate tracked `frontend/dist` only after source verification.

### Ask first

- Any backend API, database, or persisted dataset-format change.
- Adding a dependency or changing CI configuration.
- Removing a capability or workflow step.

### Never

- Hide an optional or unavailable step without explaining the path forward.
- Use completion state to block users from revisiting later steps.
- Unmount active background-job orchestration merely because a different step
  is visible.
- Break historical dataset workspace links.

## Success criteria

- At every dataset URL exactly one workflow step is visible as the page's main
  task.
- Character, Concept, and Style flows contain every applicable guide step in
  the documented order.
- Refreshing or copying a canonical step URL reopens the same dataset and step.
- Back, Continue, and Skip lead to the correct neighboring applicable step.
- The navigator truthfully communicates progress and optional/unavailable state.
- Existing background work continues while the user changes steps.
- Old section/panel URLs land on the closest new step.
- The first-run guide names the exact routes, headings, and controls users see.
- Unit, frontend gate, and critical Playwright tests pass with no console or
  accessibility errors introduced by the workflow shell.

## Non-goals

- Changing setup, settings, provider routing, backend processing, or dataset
  storage.
- Redesigning individual image cards, training algorithms, or Studio.
- Preventing advanced users from jumping directly to any applicable step.
