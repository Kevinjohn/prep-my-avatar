# Versioning and releases

Prep My Avatar uses calendar versioning for the application and SemVer only for
reusable packages.

## Application CalVer

Application releases have the form `YYYY.MM.DD.N`:

- `YYYY.MM.DD` is the release date in the Europe/London project timezone.
- `N` starts at `1` and increments for each additional release that day.
- Git release tags add a leading `v`, for example `v2026.07.17.1`.
- `backend/app/version.py` is the single source of truth for the running app,
  diagnostics, exported provenance, portable bundles, and update checks.

Versions are parsed as numeric calendar components. They are not compared as raw
strings, so `2026.07.17.10` correctly sorts after `2026.07.17.9`. Older three-part
date tags remain readable as release zero for that date.

## Independent package versions

- `pyproject.toml` versions the prototype `avatar_prep` Python library with SemVer.
- `frontend/package.json` contains internal package/build metadata required by the
  JavaScript toolchain.
- Neither package value is the application version shown to users.

## Cutting a release

1. Choose today's CalVer and update `APP_VERSION` in `backend/app/version.py`.
2. Update the current application release in `README.md`.
3. Run the backend tests and frontend tests, then rebuild `frontend/dist/`.
4. Commit the complete release with `Release vYYYY.MM.DD.N` as the subject.
5. Create an annotated `vYYYY.MM.DD.N` tag pointing to that commit.
6. Push the commit and tag when ready to publish.

The GitHub release workflow checks that the tag exactly matches `APP_VERSION`
before it tests and builds the portable Windows bundle.
