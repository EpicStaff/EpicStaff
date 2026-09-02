# Style tokens refactor — plan & progress

Goal: replace hardcoded colors (hex/rgba) in component `.scss` files with
`var(--...)` references from [`src/styles/_variables.scss`](src/styles/_variables.scss),
so a color used by many components can be changed in one place.

Rules while working through this list:
- `_variables.scss` can be edited when needed (new token, or migrating a
  `LEGACY` var to a proper primitive) — always called out per phase below.
- Each phase = one review checkpoint. Don't start the next phase until the
  current one is reviewed.
- "Hardcoded colors" counts are from a rough grep of hex/rgba literals in
  `.scss` files, taken 2026-09-02 — a sizing guide, not exact.

## Status

- [x] **Phase 0 — Fix `_variables.scss` regressions** (2026-09-02)
  Restored ~40 variables that the in-progress token draft had deleted while
  still being referenced by components (`--color-ks-*`, `--text`,
  `--text-secondary-60`, `--color-error`, `--purple-primary`, `--orange`,
  `--red`, `--inactive-purple`, `--color-nodes-sidepanel-bg`, etc. — see the
  `LEGACY` block at the bottom of `:root` / `.my-app-light`). Values copied
  verbatim from the old file, so this is a zero-visual-diff safety net, not
  a real migration. Verified: every var used anywhere in the app now
  resolves to something defined in `_variables.scss`.

- [x] **Phase 1 — Auth pages + Not-found** (2026-09-02, pending your review)
  `features/auth/**`, `pages/not-found-page/**`. Replaced 7 hardcoded
  colors with tokens (`--color-text-primary`, `--color-text-subtle`,
  `--color-text-secondary`, `--graphite-950`, `--indigo-alpha-30`). Added
  two new primitives, since no existing token matched exactly:
  `--graphite-810: #25262a` (onboarding choice-card hover background) and
  `--indigo-alpha-30: rgba(101, 98, 245, 0.3)` (auth spinner ring).

- [x] **Phase 2 — Layouts** (2026-09-02, pending your review)
  Only `sidenav.component.scss` had hardcoded colors (`main-layout.component.ts`
  and `routed-auth-shell.component.ts` have no stylesheets; `tooltip.component.scss`
  was already clean). Replaced 8 values, all exact matches to existing
  tokens — no new tokens needed: `var(--white)`, `var(--white-alpha-5)` x2,
  `var(--purple-alpha-15)` x2, `var(--gray-400)`, `var(--gray-200)`,
  `var(--accent-color)`.
  Finding: `.my-app-light` (light theme) is defined in `_variables.scss` but
  never applied anywhere in the app — no toggle exists, so it's currently
  dead/unreachable. Only the dark theme needs visual review for now.

- [x] **Phase 3 — Shared UI-kit components** (~80 files, ~366 hardcoded colors)
  `shared/components/**`. Foundational — reused on every page. Split into
  sub-batches by directory size since it's too big for one review pass. No
  isolated component gallery, so each sub-batch lists concrete pages to
  check.

  - [x] **3.1 — small components (<=2 colors each)** (2026-09-02, pending review)
    `buttons`, `copy-button`, `avatar-upload`, `create-agent-form-dialog`,
    `password-strength`, `save-with-indicator`, `textarea`,
    `unsaved-indicator`, `webhook-trigger-field`, `go-to-button`,
    `chips-input`, `label-color-picker`, `listbox`, `pagination-controls`,
    `tab-button`, `webhook-trigger-dialog`.
    14 hardcoded colors replaced, all exact matches except two new tokens:
    `--red-540: #e53935` (textarea invalid border, one-off) and
    `--red-450` / `--red-450-alpha-10: rgba(255, 77, 79, 0.1)` (a distinct
    error-red used in ~13 files app-wide — added now so later phases reuse
    it instead of re-adding).
    Skipped (already fine, no visual effect): a commented-out line in
    `buttons`; a fully-transparent (`alpha: 0`) local var in
    `avatar-upload`; two `var(--token, #hexFallback)` spots in
    `create-agent-form-dialog` and `go-to-button` where the primary token
    already matches and the fallback is unreachable dead code.
    Note: `listbox` (`app-listbox`) has no usages anywhere in the app —
    looks like dead code, can't be visually tested.

  - [x] **3.2 — medium components** (2026-09-02, pending review)
    `radio-button`, `knowledge-selector`, `label-sidebar`,
    `timezone-selector`, `range-slider`, `select`, `webhook-trigger-select`,
    `forms/footer`, `forms/icon-selector`, `forms/process-selector`,
    `time-picker`, `round-button`, `unsaved-changes-dialog`.
    ~30 hardcoded colors/keyword-colors replaced. New tokens added (none
    matched exactly): `--slate-400` / `--slate-700` (select spinner),
    `--crimson-500: #ef4444` (a "danger red" used in 9 other files app-wide),
    `--scarlet-500` / `--scarlet-700` (Material red 500/700, danger button),
    `--amber-450: #ffb400` (warning icon), `--graphite-880: #1e1e22`
    (round-button tooltip bg), `--gray-810: #202020` (active-state text on
    accent bg — also matches a color in `json-editor`, to be wired up when
    that file's own phase comes). Also replaced the CSS keyword `white` with
    `var(--white)` everywhere it appeared in this batch.
    Found 4 more dead/unused shared components (in addition to `listbox`
    from 3.1): `knowledge-selector`, `range-slider` (a *different*,
    unrelated component in `pages/chats-page` happens to reuse the same
    selector/class name and has its own separate styles), `forms/footer`,
    `forms/process-selector` — none are referenced anywhere in the app.

  - [x] **3.3 — dropdowns/pickers** (2026-09-02, pending review)
    `action-dropdown-button`, `label-dropdown`, `multi-select`, `date-picker`,
    `key-value-list`, `filter` (both dialogs), `number-stepper`,
    `voice-selector`.
    ~45 hardcoded colors replaced, mostly exact matches to existing tokens.
    New tokens added (none matched exactly): `--gray-110: #ededed` and
    `--blue-450: #1e72e6` (both also appear in 2 chats-page files, will be
    reused when Phase 10 gets there).

  - [x] **3.4 — dialogs/editors** (2026-09-02, pending review)
    `cofirm-dialog`, `form-controls` (slider + toggle-switch),
    `select-dropdown`, `slider-with-stepper`, `dynamic-table`,
    `date-range-picker`, `json-editor`.
    ~55 hardcoded colors replaced. Notable finding: `cofirm-dialog`
    (confirmation-dialog.component.scss) declared its own `--color-text`,
    `--color-text-subtle`, `--color-nodes-sidepanel-bg` at **global `:root`**
    scope (not `:host`) — and `--color-nodes-sidepanel-bg` there held a
    *different* value (`#1e1e1e`) than the real shared token (`#222225`).
    Removed that block entirely and pointed the dialog straight at
    `--graphite-875` (the primitive matching its actual `#1e1e1e`), so it no
    longer risks leaking a conflicting global override.
    Lots of new tokens this batch (each is an exact value with no existing
    match): `--gray-450`, `--gray-460`, `--gray-215` (+ alpha), `--gray-820`,
    `--gray-830` (+ alpha), `--gray-110`(carried from 3.3), `--graphite-660`,
    `--graphite-870`, `--graphite-885`, `--azure-500`, `--gold-500`,
    `--lavender-500`, `--red-420`, `--red-460` (+ alphas), `--red-580`,
    `--purple-alpha-7`, `--white-alpha-3-flat` (genuinely different from the
    existing `--white-alpha-3`, which is `0.0314` not `0.03` — kept both
    rather than merging).
    Also found `json-editor`'s own `#202020` hover matches `--gray-810`
    (added back in 3.2 for `process-selector`) — wired it up now.
    Found another dead component: `form-controls/slider` (`app-form-slider`)
    — no usages anywhere.

  - [x] **3.5 — dual-slider** (2026-09-02, pending review)
    Turns out every other remaining shared-component dir (~43 of them —
    icons, checkbox, table, spinners, tooltips, etc.) already had zero
    hardcoded colors. Only `dual-slider` and `llm-dialogs` were left.
    Replaced 14 colors in `dual-slider.component.scss`, all exact matches
    to existing tokens except one: `--cyan-460: #00d4ff` (first-handle thumb
    color, close to but distinct from the existing `--cyan-500: #00dddd`).

  - [x] **3.6 — `llm-dialogs`** (2026-09-02, pending review) — closes out
    Phase 3 entirely.
    9 files, ~35 real replacements (the rest of the ~83 counted colors were
    `var(--token, #fallback)` dead-code fallbacks — the 4 `create-*-modal`
    dialogs share near-identical markup/styles). All exact matches to
    existing tokens except `--gray-455: #acacac` (llm-model-selector
    provider-name text, one-off).
    Found 4 more dead components: `create-embedding-model-modal`,
    `create-llm-model-modal`, `create-realtime-model-modal`,
    `create-transcription-model-modal` — none referenced anywhere in the
    app (not even via a service/factory). Combined with the 6 found in
    3.1-3.4 (`listbox`, `knowledge-selector`, `range-slider`,
    `forms/footer`, `forms/process-selector`, `form-controls/slider`),
    that's 10 unused components sitting in the shared kit — worth a cleanup
    pass at some point, separate from this refactor.

  **Phase 3 complete.** All ~80 shared component dirs now use tokens from
  `_variables.scss` (or had none to begin with).

- [x] **Phase 4 — Projects list + Tools list** (2026-09-02, pending review)
  `features/projects/pages/projects-list-page/**`, `features/tools/pages/tools-list-page/**`
  Only 8 files exist here (my-projects/templates subcomponents have no
  stylesheets of their own). 5 hardcoded colors replaced, all exact matches
  except one new token: `--iris-500` / `--iris-alpha-8: rgba(88, 86, 214, 0.08)`
  — a distinct purple (not the app's actual `--purple-500`/accent-color)
  used for "active" tint backgrounds. Also appears in `flows-list-page` and
  `files` storage-preview — will be reused in Phase 9 and 12.

- [x] **Phase 5 — Workspace + Profile** (2026-09-02, pending review)
  `features/role-base-access/**`. 5 hardcoded colors replaced across 4
  files, all exact matches to existing tokens — no new tokens needed
  (`--black-alpha-40` x2, `--black-alpha-24`, `--white`, `--green-400`).

- [x] **Phase 6 — Agent definitions** (2026-09-02, pending review)
  `features/agent-definitions/**`. ~55 hardcoded colors replaced across 11
  files (the rest of the ~69 counted were `var(--token, #fallback)`
  dead-code). New tokens: `--red-490: #e5484d` (recurs in
  `webhook-trigger-select` too, Phase 3) and `--green-450: #2ecc71`
  (surface-usage-dialog status dot, one-off). Everything else was an exact
  match to existing tokens (`--graphite-750`, `--graphite-900`,
  `--fog-alpha-16`, `--purple-alpha-40`, etc.) — `rgba(43, 45, 48, 1)`
  turned out to be `--graphite-750` at full opacity, used 11 times in one
  file (`surface-card.component.scss`).

- [x] **Phase 7 — Staff page** (2026-09-02, pending review)
  `pages/staff-page/**`. ~85 hardcoded colors replaced across 9 files.
  Notable: 5 of the files (the LLM/tool selector popups + agents-table)
  turned out to be a self-contained mini design system using **local SCSS
  `$variables`** (`$accent-blue: #4f46e5`, `$bg-item: #2a2a2a`, etc.)
  instead of CSS custom properties — meaning the "one place to change a
  color" goal was already broken for them even though the code looked
  DRY within each file. Rewrote those 5 files to reference `_variables.scss`
  tokens directly and dropped the local `$color` variables (kept
  `$transition-default`, since that's not a color). One SCSS `color.adjust()`
  hover-lighten call was swapped for a `color-mix()` equivalent so it can
  target a CSS var.
  Many new tokens (mostly one-offs or recurring across the codebase, not
  yet unified): `--indigo-500/600` (+3 alphas) — recurs in ~10 files,
  `--gray-105/118/222/240/440/475`, `--sky-600`, `--orange-600` (the literal
  CSS `orange` keyword — different from the existing legacy `--orange`
  token!), `--stone-950-alpha-35`, `--red-450-alpha-35/95`,
  `--graphite-1000-alpha-70`, `--graphite-890/790/670`, `--red-425/430/950`.
  Also fixed one color I'd missed on the first pass in
  `advanced-settings-dialog.component.scss` (a bare `color: white;`).

- [x] **Phase 8 — Knowledge sources** (2026-09-02, pending review)
  `features/knowledge-sources/**`. Migrated all `var(--color-ks-*)` usages
  (~100 occurrences across all 24 files) to the real semantic/primitive
  tokens they aliased to (`--color-ks-text` → `--color-text-primary`,
  `--color-ks-button-activated` → `--accent-color`,
  `--color-ks-status-failed` → `--color-status-failed`, etc. — see the sed
  mapping used, or `_variables.scss`'s LEGACY block for the old values).
  Plus 10 directly hardcoded colors replaced (5 new tokens: `--sky-950`,
  `--graphite-895`, `--yellow-alpha-30`, `--orange-600-alpha-60`,
  `--amber-600` + 2 alphas).
  **Finding:** ~70 other files across the app still reference
  `var(--color-ks-*)` — some in already-closed phases (auth, role-base-access,
  agent-definitions, shared components), most in phases not yet reached
  (files, chats, running-graph, flows, visual-programming, configure-models).
  Left those alone — the legacy vars still resolve correctly, so nothing is
  broken; they just weren't in scope for phases already reviewed. Migrate
  each one when its own phase comes up, per the original Phase 0 note.
  Did NOT remove the `--color-ks-*` block from `_variables.scss` yet since
  it's still load-bearing for those ~70 files.

- [ ] **Phase 9 — Files** (~10 files, ~138 hardcoded colors)
  `features/files/**`

- [ ] **Phase 10 — Chats** (~15 files, ~103 hardcoded colors)
  `pages/chats-page/**`

- [ ] **Phase 11 — Running graph** (~5 files, ~93 hardcoded colors)
  `pages/running-graph/**`

- [ ] **Phase 12 — Flows (list/templates)** (~20 files, ~231 hardcoded colors)
  `features/flows/**`

- [ ] **Phase 13 — Open project page** (~13 files, ~205 hardcoded colors)
  `open-project-page/**`

- [ ] **Phase 14 — Visual programming (flow canvas)** (~44 files, ~712 hardcoded colors)
  `visual-programming/**`. Biggest and riskiest — last on purpose.

## Notes / decisions log

- 2026-09-02: Phase 7 turned up a bare CSS named-color keyword (`orange`,
  not `var(--orange)`) that earlier greps for hex/rgba/white/black missed.
  From now on also grep for other plain CSS color keywords
  (`orange`, `red`, `green`, `blue`, `gray`/`grey`, etc. used bare, not as
  `var(--x)`) when scanning a phase's files, not just hex/rgb(a)/white/black.

- 2026-09-02: Rule confirmed — never consolidate a hardcoded color into a
  visually-similar-but-different existing token. If no token matches the
  exact value, add a new one to `_variables.scss` instead. (Reverted an
  earlier Phase 1 edit that had mapped `rgba(101, 98, 245, 0.3)` onto
  `--purple-alpha-30` "because it looked like a faded accent color" — added
  `--indigo-alpha-30` with the exact value instead.)

- 2026-09-02: Someone (a prior session) had already started restructuring
  `_variables.scss` into primitives + semantic tokens before any page work
  began, and in doing so silently deleted several still-used variable
  names. Phase 0 restored them as a literal-value `LEGACY` block rather
  than immediately re-aliasing to new primitives, to guarantee zero visual
  diff. Each LEGACY var should be migrated (aliased to a primitive, or
  renamed at call sites) as part of the phase that owns its pages —
  cross-reference the table above.
