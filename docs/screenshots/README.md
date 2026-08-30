# Screenshot archive

The `guide/` directory contains the current, genuine screenshots used by the
flat first-run HTML guide. Each image is captured at 1440×900 from an isolated
temporary app instance with neutral fixture data. Run `pnpm run capture:guide`
from `frontend/` to refresh the complete set, then update each digest and
capture revision in `manifest.yml`.

The guide itself is plain HTML and CSS. Screenshot capture is a maintainer tool;
it is not a runtime dependency and it does not generate the documentation.

The `readme/` directory is an unverified visual archive. None of its images is
current product documentation unless it has a `current` record in
`manifest.yml`; documentation validation rejects any referenced image without
such a record. The current README therefore contains no screenshot claims.

The numbered PNG files (`01-create.png` through `06-scraper.png`) are retained
as a historical snapshot of the inherited LoRA Dataset Studio workflow. They
are not current product documentation and should not be reused without a fresh
capture and manifest entry.
