# Getting help & reporting problems

Stuck, found a bug, or missing a feature?

- **GitHub** — [Prep My Avatar issues](https://github.com/Kevinjohn/prep-my-avatar/issues)
  is the supported destination for reproducible bugs and feature requests; the
  templates walk you through what to include.
- **Upstream community** — the inherited application's
  [Discord](https://discord.gg/j6hnJBFtXE) may help with LoRA Dataset Studio
  behavior, but it does not own or support this fork's changes.

---

## What makes a report solvable

The difference between a five-minute fix and a week of guessing is almost
always the same four things:

1. **Version** — shown in Settings → Maintenance → Updates ("Current build").
2. **Environment** — OS, and whether you run API-only, full local, or Docker.
3. **What you did → what you expected → what happened** — three short lines
   beat three paragraphs.
4. **The log** — the last lines of the server log usually name the real error.
   Settings → Maintenance → 🪵 Server log → **Copy all**.

## Or let the app write it for you

The **diagnostic report** button below assembles all of that in one click:
version, OS, capability status, non-secret settings and the last log lines —
formatted, copied to your clipboard, ready to paste into Discord or a GitHub
issue in this repository.

What it deliberately **never** includes: your API keys or tokens (only
whether each one is set) and your folder paths (only whether each one is
configured). One caveat: the log tail can mention file names from your machine
— skim the paste before posting if that matters to you.

## Feature requests

Describe the **job you were doing when you missed the feature** — the problem
is more valuable than the proposed solution. Open a GitHub issue with the
*Feature request* template.
