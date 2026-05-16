## Summary

<!-- One paragraph: what this PR does and why. -->

Closes #

## Context for reviewers / AI agents

<!-- Optional: constraints, design decisions, files to focus on. -->

- **Area:** <!-- scraper / API / UI / CLI / storage / tests / CI -->
- **Key paths:** <!-- src/<package>/... -->
- **Template upstream:** <!-- if fix belongs in beetrackr-template, link issue/PR there -->

## Changes

-

## Test plan

- [ ] `pytest tests/ -q` (or targeted: `pytest tests/test_... -q`)
- [ ] Manual smoke test:
  ```bash
  # e.g. <cli> scrape -p <provider> --limit 2
  # e.g. <cli> serve → exercise /ui/records
  ```
- [ ] `make test` / `make lint` (if using Makefile)
- [ ] No secrets or `.env` committed

## Checklist

- [ ] Tests added or updated where behavior changed
- [ ] Ported to **beetrackr-template** if this should ship in the Copier scaffold
- [ ] README / `config.yaml` updated if user-facing behavior changed
- [ ] Focused diff — no unrelated refactors
- [ ] Pre-commit / lint passes locally

## Screenshots / logs

<!-- UI changes, API errors fixed, sample CLI output. Delete if N/A. -->
