<!--
Thanks for contributing! Keep PRs small and focused.
For anything non-trivial, please open an issue or chat on Discord first — see CONTRIBUTING.md.
-->

## What & why

<!-- What does this change, and what problem does it solve? Link the issue or Discord thread if there is one. -->

Closes #

## How I tested

- [ ] `python -m pytest backend/tests tests -q` passes (Python changes)
- [ ] `python -m ruff check backend src tests` passes (Python changes)
- [ ] Frontend `pnpm run gate` passes and I committed regenerated `frontend/dist/` (frontend changes)
- [ ] Frontend `pnpm run e2e` passes (user-flow changes)
- [ ] N/A items above are explained because this is docs/config-only or the check is outside the change's scope

## Screenshots

<!-- Required for any UI change. Before/after if you changed something that already existed. -->

## Checklist

- [ ] Small and focused — one change per PR
- [ ] UI text is in English
- [ ] **No secrets or local paths** in the code, screenshots, logs, or this description (no API keys, tokens, `config.json`, `.env`, absolute machine paths)
- [ ] I read the [Contributing guide](../CONTRIBUTING.md)
