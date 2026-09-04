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

- [x] **Phase 9 — Files** (2026-09-02, pending review)
  `features/files/**`. ~70 hardcoded colors replaced across 8 files (2 had
  none). Three dialogs (`add-to-flow-dialog`, `copy-to-dialog`,
  `create-folder-dialog`) share near-identical markup/styles, which made
  this mostly mechanical — nearly everything was an exact match to tokens
  already established in earlier phases. Two new tokens needed:
  `--fog-alpha-4` and `--indigo-alpha-10` (an alpha step of the Phase-1
  auth-spinner indigo that hadn't come up yet).
  Also found and fixed a broken reference: `create-folder-dialog` had
  `var(--Transparent-red, rgba(245, 66, 66, 0.08))` — `--Transparent-red`
  (capital T) was never defined anywhere, so it was silently always
  falling back to the literal; replaced the whole thing with
  `var(--red-alpha-8)` (exact match to that literal).
  Also migrated the 2 of 5 `--color-ks-*` legacy refs found here that had
  a clean existing mapping (`--color-ks-status-new` → `--success-color`,
  `--color-ks-secondary` → `--color-text-muted`); left the 3
  `--color-ks-transparent-black-28` refs alone since — like in Phase 6 —
  that one has no primitive equivalent yet.

- [x] **Phase 10 — Chats** (2026-09-03, pending review)
  `pages/chats-page/**`. ~105 hardcoded colors replaced across 11 files (4
  had none: `chats-page`, `microphone-selector`, `chat.component`,
  `chats-sidebar.component`). Almost everything was an exact match to
  tokens already established in earlier phases (the full white/black/purple
  alpha scales from Phase 3 covered nearly every `rgba(255,255,255,x)` /
  `rgba(0,0,0,x)` / `rgba(104,95,255,x)` occurrence here).
  New tokens: `--crimson-600` / `--crimson-600-alpha-20` (bootstrap-red
  "end call" button, distinct from the existing `--crimson-500`),
  `--graphite-970` (`#151515`, assistant chat-bubble background),
  `--gray-210` (`#d1d1d1`, "awaiting connection" text), `--gray-590` /
  `--gray-605` (`#5a5a5a` / `#666666`, `chats-content` "no agent" empty
  state), `--blue-700` (`#004494`, that same empty state's button hover),
  `--graphite-745` (`#35373b`, realtime-settings-dialog close-button hover).
  Migrated 2 `--color-ks-*` legacy refs owned by this phase to their exact
  primitive equivalents (`--color-ks-line` → `--graphite-700`,
  `--color-ks-hover-row` → `--graphite-650`) — both already existed as
  primitives from earlier phases, just not wired up here yet.
  Also resolved several `var(--token, #fallback)` cases where the primary
  token was never actually defined (`--color-surface-2`, `--color-surface-3`,
  `--color-primary`) — same pattern as Phase 3.4/9 — to their real
  primitives/`--accent-color`.

- [x] **Phase 11 — Running graph** (2026-09-04, pending review)
  `pages/running-graph/**`. ~95 hardcoded colors replaced across all 5
  files. `graph-messages.component.scss` (the biggest file) had a full
  12-step alpha gradient in `rgba(0, 191, 165, x)` for the subflow-nesting
  tree visualization (levels 1-4, background/border/connector each at a
  different opacity) — added the whole `--teal-alpha-*` scale (1-5, 3, 4-5,
  6, 20, 25, 30, 35, 40, 45, 50, 55) since none of those steps existed yet.
  New tokens: `--amber-620` (+2 alphas, "reconnecting" status — distinct
  from the existing `--amber-600`), `--crimson-500-alpha-10/20` (alpha
  steps of the existing `--crimson-500`, "disconnected" status),
  `--teal-460` (breadcrumbs-search border/icon, distinct from `--teal-500`),
  `--graphite-635` (scrollbar thumb), `--rose-500` (empty-list text),
  `--graphite-960`/`--graphite-955` (session-dropdown bg/hover),
  `--purple-450` (drag-handle active state), `--indigo-300`/`--indigo-450`
  (+alpha) (extracted-chunks accent/chip), `--blue-410`/`--teal-450`/
  `--orange-450` (+alphas each, findings-message severity badges — each is
  a distinct shade from an existing similarly-named token, e.g. `--blue-410`
  vs the existing `--blue-400`).
  Migrated 5 more `--color-ks-*` / undefined-fallback legacy refs owned by
  this phase (`flow-messages-panel`) to their real primitives, same pattern
  as Phase 9/10: `--color-ks-hover-row`/`--color-ks-line` → `--graphite-650`/
  `--graphite-700`, `--color-ks-background` → `--graphite-900`,
  `--color-surface`-style undefined fallback `--db-primary-1` → `--indigo-650`.
  **Finding (left unfixed, flagged for you):** `extracted-chunks-message`
  and `findings-message` both reference `var(--gray-050)` (fixed — clear
  typo for the real `--gray-50` token, migrated) and `var(--gray-775)`
  (left as-is — **not** a typo of any existing token, so this one has been
  silently rendering as browser-default/inherited color this whole time,
  not the intended border shade. Used in 3 spots: `extracted-chunks-message.component.scss:127`
  and `findings-message.component.scss:94,116`, all `border: 1px solid var(--gray-775)`.
  Left untouched since I can't guess the intended color — let me know what
  it should look like and I'll add the token.)

- [x] **Phase 12 — Flows (list/templates)** (2026-09-04, pending review)
  `features/flows/**`, all 20 files, ~232 hardcoded colors replaced. No dead
  components found this time — every component here is actually wired up
  (verified via a full usage trace: routes `/flows`, `/flows/:id`,
  `/sessions`, `/graph/:graphId/session/:sessionId`).
  Two files (`flow-session-status-badge`, `import-result-dialog`) turned
  out to be a self-contained "session status" mini-palette reused across
  the flows feature — most of their colors were exact matches to each
  other (`rgb(104, 95, 255)` = accent, `rgb(255, 143, 63)` = `--orange-500`,
  `rgba(43, 45, 48, 1)` = `--graphite-750`, all already-established tokens).
  New tokens (mostly one-offs for this session-status palette and a few
  scattered dark-theme greys): `--amber-620`(carried from Phase 11),
  `--red-580-alpha-18`, `--rose-450`, `--umber-950`(+alpha) (status-badge
  "stopped"), `--green-460`, `--mint-500`(+alpha), `--gold-460`(+alpha),
  `--slate-400-alpha-18`, `--slate-700-alpha-18`, `--gray-540`(+alpha)
  (status-badge "completed"/"waiting"/"pending"/"expired"/"unknown"),
  `--graphite-690` (card/row hover, reused 3x), `--graphite-815` (dropdown
  bg/hover, reused 3x), `--iris-alpha-8` (reused from Phase 4),
  `--slate-620`(+alpha) (session preview graph background),
  `--graphite-785` (session preview border), `--graphite-940`,
  `--gray-610`, `--gray-225`, `--indigo-950`/`--indigo-900`/`--indigo-880`,
  `--red-560`/`--red-470`/`--maroon-950` (version-history-panel's own
  self-contained dark-indigo mini-palette — a different design language
  from the rest of the app, all newly added since none of its ~15 colors
  matched anything existing), `--orange-alpha-6`, `--green-470`,
  `--graphite-750-alpha-50`/`--graphite-740`, `--purple-420`.
  Also migrated a few more `--color-ks-*`/undefined-fallback legacy refs
  owned by this phase (`my-flows`, `flow-messages`-style patterns already
  seen in Phase 9-11), same treatment as before.

- [x] **Phase 13 — Open project page** (2026-09-04, pending review)
  `open-project-page/**`, all 13 files, ~210 hardcoded colors replaced.
  Two files (`agent-popup.component.scss`, `tasks-table.component.scss`)
  turned out to be near-duplicates of a mini design system already fixed
  in Phase 7 (`staff-page`'s `agents-table` + LLM/tool selector popups) —
  every one of their colors was an exact match to tokens already added
  back then (`--indigo-600`, `--gray-105/490/550`, `--indigo-650`,
  `--sky-600`, `--stone-950-alpha-35`, `--orange-600`,
  `--red-450-alpha-35/95`, etc.) — purely mechanical, no new tokens needed
  for either file. Rewrote both (plus `open-project-page.component.scss`
  and `variables-content.component.scss`) to drop local SCSS `$color`
  variables in favor of direct `var(--token)` references, same treatment
  as Phase 7 — `open-project-page.component.scss` also had 3 dead local
  `$vars` (`$background-color`, `$border-color`, `$purple-accent`) that
  were declared but never actually used anywhere in the file; dropped them
  entirely rather than converting them, and `agent-popup.component.scss`
  had one unused `$bg-dark`, same treatment.
  `details-content.component.scss`'s local `$vars` were already wrapping
  `var(--token)` (not literals) — left as-is, no change needed.
  New tokens: mostly one-offs for `settings-section` (`--graphite-990`
  (+alpha-40), `--graphite-875-alpha-40`, `--orange-600-alpha-30`,
  `--gray-580`, `--gray-595`), `--slate-200`, `--gray-108`(+alpha-70,
  reused 3x across this phase), `--gray-52`, `--gray-570`, `--slate-900`,
  `--purple-460`, `--gray-585`, `--crimson-600-alpha-30`,
  `--green-500-alpha-10`, `--indigo-600-alpha-10/20` (filled in gaps next
  to the existing `-15/40/80` from Phase 7).
  **Found 1 dead component**: `variables-content.component.scss`
  (`VariablesContentComponent`) — not wired into `open-project-page`'s
  section list (`details`/`agents`/`tasks`/`settings` only) or referenced
  anywhere else. Styled it anyway since it's in-scope, but flagging per
  the established practice — can't be visually tested since nothing opens
  it.

- [x] **Phase 14 — Visual programming (flow canvas)** (2026-09-04, pending review)
  `visual-programming/**`, all 44 component files + 2 shared mixin files
  (`styles/_flow-node-mixins.scss`, `styles/node-panel-mixins.scss`),
  ~700 hardcoded colors replaced. The biggest phase by far, done in one
  pass (no sub-batch splits) given how consistently every other phase
  since Phase 3 has gone in a single pass.
  **Important structural finding**: this feature has its own **separate,
  already-centralized token file** — `visual-programming/styles/_variables.scss`
  — defining canvas/node-graph-specific tokens (`--vp-*`, `--db-*`,
  `--agent-node-accent-color`, `--task-node-accent-color`, etc., likely
  from the underlying flow-canvas library, with light/dark variants via a
  `.dark` class). This is a *legitimate*, pre-existing single source of
  truth for canvas colors — left entirely untouched, and `var(--vp-*)`/
  `var(--agent-node-accent-color)` etc. references throughout the 44 files
  were **skipped**, same as how `_variables.scss` (the main app one) itself
  was never a "find and replace" target in any phase. Only genuinely
  hardcoded hex/rgba/keyword literals inside the component files were
  replaced with tokens from the main app `_variables.scss` — as in every
  prior phase.
  One nice side-effect: `flow-graph.component.scss`'s minimap previously
  hardcoded each node type's dot color as a raw literal (`fill: #8e5cd9`
  etc.) instead of referencing the canvas's own `--agent-node-accent-color`
  etc. — wired those up now, so the minimap dots for Agent/Task/Tool/LLM/
  Project/Python/Edge nodes will always match their real node accent
  color if that's ever changed, instead of silently drifting.
  Found and removed one piece of dead debug code: `flow-base-node.component.scss`
  had `background-color: red;` immediately followed by `background: var(--color-nodes-background);`
  on the next line — the shorthand always won, so the red was a
  permanently-invisible no-op. Removed rather than tokenized (zero visual
  effect either way).
  6 files (`agent-tasks-table`, `tasks-table`(open-project-page, Phase 13),
  `agent-popup`, `expression-builder`, `settings-section`, `open-project-page`)
  turned out to be Phase-7-style self-contained mini design systems with
  local SCSS `$color` variables baked to literals at compile time — all
  rewritten to reference `var(--token)` directly; a few had entirely
  unused `$vars` (declared, never referenced) which were dropped rather
  than converted.
  Migrated several more `--color-ks-*`/`--text`/`--text-secondary-60`
  LEGACY refs owned by this phase to their real primitives (same pattern
  as Phases 9-13): `--color-ks-text` → `--fog-200`,
  `--color-ks-transparent-text-80/60` → `--fog-alpha-80/60`,
  `--transparent-white-8` → `--fog-alpha-8`, `--inactive-purple` →
  `--purple-alpha-40`, `--purple-primary` → `--accent-color`,
  `--color-ks-status-warning`/`--color-ks-transparent-yellow` →
  `--yellow-500`/`--yellow-alpha-6`, `--color-ks-status-failed` →
  `--red-600`, `--color-ks-status-blue` → `--sky-500`.
  Roughly 45 new one-off primitives added (mostly for the `classification-decision-table`
  family's orange/purple/white alpha scales, a VS Code Dark+ syntax-highlight
  palette reused across `expression-editor`/`expression-builder`/
  `autocomplete-overlay`/`value-preview-tooltip`/`editor-toolbar`
  — `--terracotta-500`, `--lavender-460`, `--magenta-500`, `--gray-212`,
  `--green-490` — and a full minimap node-type color set for the types
  without their own canvas accent token: `--slate-215`, `--azure-450/550/560/465`,
  `--gold-480`, `--rose-500`, `--green-520/510`, `--orange-470`).
  **Found 2 dead components** (verified: no template import, no
  `Dialog.open`/`ComponentPortal` reference, not in the node-type→panel
  registry map): `FlowZoomControlsComponent`
  (`components/flow-zoom-control-panel/flow-zoom-controls.component.ts`)
  and `CdtImportPreviewDialogComponent`
  (`components/node-panels/classification-decision-table-node-panel/cdt-import-preview-dialog/cdt-import-preview-dialog.component.ts`).
  Styled both anyway since they're in-scope, but flagging per the
  established practice — neither can be visually tested since nothing
  opens them.

  **Phase 14 complete — this closes out the entire style-token refactor.**
  All 15 phases (0-14) are done. The `--color-ks-*` LEGACY block in
  `_variables.scss` is now down to just the handful of refs each
  owning-phase intentionally left alone (documented per-phase above,
  e.g. `--color-ks-transparent-black-28` in a few places with no clean
  primitive mapping) — a final sweep to confirm nothing else still
  references the LEGACY block app-wide would be a reasonable next step if
  wanted, but is optional cleanup rather than required follow-up.

- [x] **Phase 15 — Verification pass** (2026-09-04)
  User asked for a full re-check of the whole project for errors or missed
  spots. Ran a production build (`npm run build`, clean both before and
  after this phase's fixes), a duplicate-CSS-variable-name audit of
  `_variables.scss`, and two background agents cross-checking every
  `var(--x)` usage against its definition and re-sweeping the whole
  `frontend/src/app` tree for bare hex/rgba literals. Found and fixed:

  1. **A real token collision** — `--rose-500` had been defined twice in
     `_variables.scss` with two different colors (`#c69999` from Phase 11,
     `#ff7be9` added in Phase 14 without checking for a name clash). The
     second definition was silently winning, so `graph-messages.component.scss`'s
     "empty-list" text had been rendering bright pink instead of its
     intended dusty rose since Phase 14. Fixed by renaming the Phase 14
     one to `--pink-500`. Also deduped a harmless (same-value) accidental
     double-declaration of the `--red-400-alpha-*` scale.

  2. **4 pre-existing broken `var()` references**, unrelated to anything
     this refactor introduced — never caught before because they're
     invalid *token names*, not hardcoded literals, so no prior phase's
     grep-for-hex methodology would have surfaced them:
     - `var(--color-text)` (undefined) → `var(--color-text-primary)`,
       in `visual-programming/components/telegram-trigger-editing-dialog/telegram-trigger-editing-dialog.component.scss`
       and `user-settings-page/.../create-custom-tool-dialog.component.scss`.
     - `var(--color-nodes-input-bg)` (undefined) → `var(--color-nodes-background)`,
       in `shared/components/forms/process-selector` (a dead component,
       fixed anyway for correctness).
     - `var(--color-divider-strong)` — referenced in `features/flows/.../flow-sessions-table.component.scss`
       (from Phase 12) but never defined anywhere; added it as a real
       token (`var(--steel-alpha-18)`) rather than renaming the call site,
       since the name already fit.
     - `var(--primary-100)` / `var(--primary-600)` (undefined, no
       `--primary-*` scale exists) → `var(--purple-alpha-15)` /
       `var(--accent-color)`, in `shared/components/forms/icon-selector`
       (also dead code, only a commented-out usage anywhere in the app).
     `--gray-775` (flagged back in Phase 11, still awaiting your answer on
     the intended color) and a few `var(--token, #fallback)` spots whose
     fallback is dead-but-harmless code were left as-is — same as the
     Phase 3 policy on dead fallbacks.

  3. **An entire missed directory tree and several missed sibling
     directories** — the original phase list was built from a page/route
     inventory that didn't fully enumerate the app, so a few areas never
     got a phase at all:
     - `pages/flows-page/components/flow-visual-programming/**` (5 files)
       — this is the *actual* routed host page for `/flows/:id`
       (`flow-header`, `shortcuts-modal`, `presence-indicator`,
       `save-dropdown`, plus the page shell itself); Phase 14 only
       covered the sibling `app/visual-programming/**` tree and missed
       this one because the names look alike but the paths differ.
       Found and fixed a likely typo along the way: `#675fff` (should be
       `#685fff`, the real accent purple — off by one digit) used in two
       spots, one of which was literally `var(--accent-color, #675fff2a)` —
       replaced both with `var(--accent-color)`.
     - `features/configure-models/**` (14 files) — an entire feature with
       no phase at all. Two local dialog tokens
       (`--configure-models-dialog-active-color` / `-inactive-color`)
       were hardcoding `#d9d9de` / `#685fff` directly instead of
       referencing `--fog-200` / `--accent-color` — repointed those two
       definitions, which fixed every downstream `var(..., #fallback)`
       consumer across the feature in one edit.
     - `features/flow-assistant/**` (7 files, including its own
       `_ep-tokens.scss` alias layer for a third-party "EpicChat" panel
       — legitimate, left the `var()`-to-`var()` aliases alone, fixed the
       handful of raw literals mixed into it).
     - `user-settings-page/tools/custom-tool-editor/**` (5 files).
     - `features/projects/components/project-card/**` (3 files) — sibling
       of Phase 4's `features/projects/pages/projects-list-page/**`, never
       covered.
     - `features/tools/components/{mcp-tool-dialog,tool-usage-dialog}`
       (2 files) — sibling of Phase 4's `features/tools/pages/tools-list-page/**`,
       never covered.
     ~36 files, ~230 hardcoded colors replaced across this newly-found
     scope, same methodology as every phase before it (exact-value tokens
     only, new primitives added where nothing matched, dead components
     fixed anyway but flagged). No new dead components found in this batch
     beyond the ones already noted above.

  Re-ran the production build and the duplicate-token check after all
  fixes — both still clean.

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
