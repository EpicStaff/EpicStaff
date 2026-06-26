# Modifications to GraphRAG (vendored)

This directory contains a vendored copy of **GraphRAG** by Microsoft Corporation,
distributed under the MIT License (see `LICENSE`).

This file documents the changes EpicStaff has made to the vendored source, in
satisfaction of the MIT License attribution requirement (MIT §3 — the requirement
to preserve the copyright/permission notice and indicate modifications). The
original MIT copyright notice is retained unchanged in `LICENSE`.

## Upstream

- **Project:** GraphRAG — https://github.com/microsoft/graphrag
- **Version forked:** `2.7.0` (see `pyproject.toml`, `[project].version`)
- **Vendored into EpicStaff:** 2026-02-23 (commit `0b32ef8d5`, "chore(EST-854-BE): commit graphrag library source files")
- **License:** MIT — Copyright (c) Microsoft Corporation. Full text in `LICENSE`.

## Modified files

All EpicStaff modifications relative to the vendored 2.7.0 baseline are listed
below. Files not listed here are unmodified copies of upstream 2.7.0.

- `graphrag/utils/api.py` — `load_search_prompt()` now treats `prompt_config` as raw prompt text when it is not a resolvable file path on disk (previously only a file path was accepted), wrapped the disk read in a guarded `try/except` so a non-path value falls through to being used as the prompt text. Changed 2026-03-26 through 2026-04-01 (commits `1de0e9368`, `e0773060f`, `0747b725b`, `f01036477`).

## Notes

- No files were added to or removed from the upstream package tree; the change set
  is confined to the single file above.
- To regenerate this list against current `HEAD`:
  ```
  git log --oneline -- src/knowledge/libraries/graphrag/
  git diff 0b32ef8d5 HEAD -- src/knowledge/libraries/graphrag/
  ```
