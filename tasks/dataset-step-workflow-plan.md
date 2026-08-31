# Dataset step workflow implementation plan

## Delivery order

1. Define and test the canonical step registry, applicability rules, route
   normalization, resume policy, and legacy mappings.
2. Bind `/datasets/:datasetId/:step` to `useDataset`, including direct loads,
   dataset creation/opening, closing, and old query-string links.
3. Add the shared step navigator and page actions with responsive and accessible
   states.
4. Convert the workspace from section visibility to step visibility. Give the
   photo review, anchors, and coverage modes; separate export from
   backup and curation from face scoring.
5. Add unit, component, and Playwright coverage for all routes and dataset kinds.
6. Update every affected first-run page and regenerate tracked frontend output.
7. Run the complete frontend gate, browser verification, and a five-axis diff
   review before committing and pushing.

## Risks and mitigations

- **Background jobs stop when pages change:** keep `DatasetWorkspace` and its
  training orchestration mounted; routes change visible step state only.
- **Direct URLs race persisted selection:** make the route dataset id
  authoritative and explicitly open it before rendering the workspace.
- **Huge component merely gains more conditionals:** centralize route policy in
  the registry and add focused modes to existing compound components.
- **Legacy links break:** map each old section/panel pair and cover mappings with
  unit tests.
- **Concept/Style receive character-only pages:** derive applicability from the
  dataset kind in one pure helper and test all three kinds.
- **Optional steps become invisible:** retain them with explicit optional labels,
  explanation, and Skip controls when applicable.

## Verification checkpoints

- Registry tests fail before implementation and pass after the pure workflow
  model is added.
- Route tests pass before the workspace rendering migration begins.
- Focused component tests pass after each visible-step extraction.
- `pnpm run gate` and the critical Playwright workflow pass on the final source.
- Browser checks cover 320 px and 1440 px, keyboard focus, page headings, and a
  clean console.
