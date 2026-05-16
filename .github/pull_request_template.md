## Summary

<!-- What changed in the Copier template and why. -->

Closes #

## Context for reviewers / AI agents

<!-- This repo: edit `template/` (Jinja sources). Do not only fix a one-off generated project. -->

- **Area:** <!-- copier.yml / Jinja API / scrapers / CLI / tests / Docker / docs -->
- **Template paths:** <!-- e.g. template/src/{{ package_name }}/api/query.py -->
- **Synced from beetrackr?** <!-- link PR/commit if ported from pellucidai-org/beetrackr -->

## Changes

-

## Test plan

- [ ] Fresh scaffold smoke test:
  ```bash
  copier copy <path-to-this-repo> /tmp/test-scraper
  cd /tmp/test-scraper
  uv sync --extra dev   # or: pip install -e ".[dev]"
  pytest tests/ -q
  ```
- [ ] Existing project `copier update` (if applicable) — review diff for breaking changes
- [ ] No secrets committed

## Checklist

- [ ] Changes are under `template/` (not only in a generated output folder)
- [ ] Matching fix/feature in **beetrackr** main repo (if applicable)
- [ ] Generated `.github` issue/PR templates still valid
- [ ] `copier.yml` questions / excludes updated if new optional files added
- [ ] Template README or `_message_after_copy` updated if setup steps changed
- [ ] Focused diff — no unrelated refactors

## Screenshots / logs

<!-- Copier output, generated project behavior. Delete if N/A. -->
