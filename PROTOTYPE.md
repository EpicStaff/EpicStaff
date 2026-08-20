# Prototype: DDL Domain Editor

**Branch:** `proto/ddl-domain-editor-20-08-26`
**Created:** 20-08-26
**Branched from:** `main` @ `4b491d02a` (via the empty `feat/EST-0000-ddl-domain` placeholder, now deleted)
**Status:** parked

## Idea

A small typed schema language (DDL) for defining a flow's Domain on the Start node, instead
of hand-editing raw `initialState` JSON. You write class and field declarations in a Monaco
editor with syntax highlighting, live diagnostics, hover and completions; it compiles to an
AST and emits three things from one source — the `initialState` JSON, a TypeScript interface,
and a mermaid ER diagram.

## What works

- Full compile pipeline — `lexer → parser → resolver → Schema`, with diagnostics collected at
  every stage rather than throwing.
- Three emitters off one schema: JSON, TypeScript, mermaid.
- `generate()` emits all three **best-effort even when the source has errors**, so a live
  preview keeps updating while you type.
- Monaco integration: custom DDL language registration, syntax highlighting, error markers.
- Editor intelligence: hover (`symbolAt`), completions, `describeClass`, and `suggestName`
  for did-you-mean on unknown type names.
- Bidirectional sync: merge JSON edits back into DDL source, conform values to declared
  types, infer types from JSON values.
- Reusable `<app-ddl-editor>` shared component — OnPush, `input()`/`output()`, no decorators.
- `ddlSource?: string` on `StartNodeData`, so the source text survives save/load.
- Type-checks clean. The one `tsc --noEmit` error (`Permission` in `role-base-access`) is
  pre-existing on `main` and unrelated to this work.

## What's unfinished / known-broken

- **Zero tests.** No specs for the lexer, parser, resolver, emitters, or sync. This is the
  riskiest gap — a hand-written parser with no tests regresses silently.
- **Possible settings-dialog regression.** `frontend/src/styles/_overlays.scss` deletes the
  `.settings-dialog-panel` / `.settings-dialog-backdrop` z-index rules while adding
  `.domain-dialog-backdrop`. Whether that breaks the settings dialog's stacking was never
  verified. Check before reusing any of this.
- **No backend contract.** `ddlSource` is frontend-only — nothing persists or validates it
  server-side, and it is absent from the Django model and crew `GraphData`. See the
  cross-layer field name contract in `CLAUDE.md`.
- **The language is undocumented.** There is no grammar reference, so `parser.ts` is the only
  spec for what the DDL accepts.

## Where the interesting code is

- `frontend/src/app/shared/ddl/core/index.ts:24` — `compile()` / `generate()`, the whole
  pipeline in one readable place. Start here.
- `frontend/src/app/shared/ddl/core/parser.ts` — the hand-written parser; the heart of it.
- `frontend/src/app/shared/ddl/core/service.ts:60` — editor intelligence (hover, completions,
  did-you-mean).
- `frontend/src/app/shared/ddl/sync/merge-json-into-ddl.ts` — the genuinely tricky part:
  folding JSON edits back into DDL text.
- `frontend/src/app/shared/components/ddl-editor/ddl-editor.component.ts:52` — component API.
- `frontend/src/app/visual-programming/components/domain-dialog/domain-dialog.component.ts` —
  the integration (+878 lines, the largest single change).

## To pick this up again

- Write tests for lexer/parser/resolver **before** changing anything else.
- Verify the `_overlays.scss` settings-dialog stacking regression.
- Decide whether `ddlSource` needs a real backend contract or stays a frontend convenience.
- Write a short grammar reference for the language.

---

Prototype-grade code: intentionally unrefactored, unreviewed, and not production-ready.
Do not merge this branch into `main`.
