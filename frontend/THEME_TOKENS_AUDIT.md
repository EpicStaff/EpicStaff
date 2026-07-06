# Theme Tokens Audit — Colors & Typography

> Analysis-only report. No code was changed. Goal: prepare a primitive + semantic
> token architecture that enables a future user-facing theme customization page.

## Executive Summary

| Metric | Value |
|---|---|
| Global CSS variables (dark, `:root`) | ~70 in `src/styles/_variables.scss` |
| Light theme overrides (`.my-app-light`) | 28 (many dark tokens have NO light counterpart) |
| Visual-programming variables | ~40 in `src/app/visual-programming/styles/_variables.scss` (own light/dark convention, inverted vs global) |
| Component files with hardcoded colors | **194 `.scss` files** |
| Hardcoded `#685fff` (brand purple) occurrences | **144** |
| Uses of `var(--white)` — variable is **never defined**, no fallback | **21** (broken styles) |
| Local SCSS `$` palettes duplicated across components | 10+ files (popup/table palettes copy-pasted) |
| Distinct `font-size` values | 35+ (mixed px / rem / em) |
| `font-family` variants | 16 declarations, 3 real families (Inter, JetBrains Mono + assorted mono stacks, Roboto in reset) |

---

## 1. Inventory

### 1.1 Global variables — `src/styles/_variables.scss`

Usage counts measured across `app/**` + `styles/**` (`.scss`/`.html`/`.ts`).

| Variable | Dark | Light | Uses | Semantic role |
|---|---|---|---|---|
| `--accent-color` | `#685fff` | `#685fff` | 411 | Interactive accent (buttons, links, focus) |
| `--accent-color-hover` | `#574fd6` | `#574fd6` | 49 | Accent hover |
| `--accent-color-active` | `#473fb3` | `#473fb3` | 7 | Accent pressed |
| `--color-required-asterisk` | `var(--accent-color)` | same | 10 | Form required marker |
| `--color-text-primary` | `#d9d9de` | `#1e293b` | 304 | Primary text |
| `--color-text-secondary` | `#c8ceda99` | `#64748b` | 204 | Secondary text |
| `--color-text-primary-hover` | `#ececf3` | `#0f172a` | 3 | Text hover |
| `--color-background-body` | `#212325` | `#f8fafc` | 47 | App background |
| `--color-sidenav-background` | `#222225` | `#ffffff` | 33 | Sidenav surface |
| `--color-modals-background` | `#222225` | `#ffffff` | 13 | Modal surface |
| `--color-flow-card-bg` | `#2b2d30` | — **missing** | 15 | Flow card surface |
| `--color-secondary-btn-background` | `#27272b` | `#f1f5f9` | 4 | Secondary button bg |
| `--color-secondary-btn-background-hover` | `#ffffff17` | `#e2e8f0` | 8 | Secondary button hover |
| `--color-ghost-btn-hover` | `rgba(104,95,255,.08)` | same | 26 | Ghost button hover |
| `--color-ghost-btn-active` | `rgba(104,95,255,.15)` | same | 8 | Ghost button pressed |
| `--color-input-background` | `#27272b` | `#ffffff` | 76 | Input bg |
| `--color-input-border` | `#c8ceda24` | `#e2e8f0` | 65 | Input border |
| `--color-input-text-placeholder` | `#c8ceda4d` | `#94a3b8` | 42 | Placeholder |
| `--color-components-card-border` | `#ffffff08` | `#e2e8f0` | 7 | Card border |
| `--color-divider-regular` | `#c8ceda24` | `#e2e8f0` | 40 | Divider |
| `--color-divider-subtle` | `#c8ceda14` | `#f1f5f9` | 259 | Subtle divider |
| `--color-drag-drop-active` | `rgba(15,15,15,.28)` | — **missing** | 6 | Drag overlay |
| `--color-nodes-flow-link` | `#00bfa5` | — **missing** | 2 | Flow link accent |
| `--color-nodes-flow-link-hover-bg` | `rgba(0,191,165,.08)` | — **missing** | 1 | Flow link hover |
| `--color-scrollbar-thumb` / `-hover` / `-track` | `rgba(217,217,227,.16/.24)` / transparent | light variants | 4/1/3 | Scrollbar |
| `--gray-50 … --gray-950` (13 steps) | fixed scale | — **not overridden** | ~400 total | Primitive gray scale (already primitive-style) |
| `--color-nodes-background` | `#27272b` | `#ffffff` | 34 | VP node surface |
| `--color-nodes-actionbar-bg` | `#222225` | `#f8fafc` | 2 | VP actionbar |
| `--color-nodes-actionbar-border` | `#c8ceda14` | `#e2e8f0` | 0 (unused?) | VP actionbar border |
| `--color-nodes-sidepanel-bg` | `#222225` | `#ffffff` | 19 | VP side panel |
| `--color-ks-*` (19 vars) | see below | — **all missing in light** | ~150 total | Knowledge-sources subsystem |
| `--color-error` | `#f54242` | — **missing** | 18 | Error |
| `--inactive-purple` | `rgba(104,95,255,.4)` | — missing | 2 | Disabled accent |
| `--purple-primary` | `rgba(104,95,255,1)` | — missing | 10 | Brand purple (duplicate of accent) |
| `--transparent-white-8` | `rgba(217,217,222,.08)` | — missing | 17 | Hover wash |
| `--transparent-green-8` / `--transparent-orange-8` | `rgba(42,186,107,.08)` / `rgba(255,143,63,.08)` | — missing | 3/1 | Status washes |
| `--text` | `rgba(217,217,222,1)` | — missing | 40 | Text (duplicate of `--color-text-primary`) |
| `--text-secondary-60` | `rgba(217,217,222,.6)` | — missing | 50 | Secondary text (near-duplicate) |
| `--color-storage-icon` | `rgba(230,230,230,1)` | — missing | 1 | Storage icon |

Knowledge-sources block (`--color-ks-*`): `primary #0a0a0a`, `secondary #666666`,
`tetriary #cccccc`, `quarternary #f5f5f5`, `white #ffffff`, `card-background #1e1e1e`,
`background #212325`, `text #d9d9de`, `button-activated #685fff`, `line #2c2c2e`,
`hover-row #3a3e48`, 10 transparent variants, 6 status colors
(`blue #48cbff`, `completed #685fff`, `new #2aba6b`, `warning #ffcf00`,
`processing #ff8f3f`, `failed #dc5b60`).

### 1.2 Visual-programming — `app/visual-programming/styles/_variables.scss`

~40 `--vp-*`, `--db-*`, `--*-node-accent-color` variables. Key facts:

- **Inverted theme convention**: base `:root` here holds *light* values, `.dark`
  holds dark — the opposite of the global file (`:root` = dark, `.my-app-light` = light).
- `--db-primary-1` is defined **twice** in the same block (`#3e63dd` then `#5672cd`) —
  the second silently wins (lines 31/34 and 80/83).
- `--schedule-trigger-node-accent-color: var(--color-ks-status-processing)` —
  cross-subsystem coupling (VP node depends on knowledge-sources status token).
- Node accents: agent `#8e5cd9`, task `#30a46c`, tool/default `#9f6a00`,
  llm `#e0575b`, project `#5672cd`, python `#ffcf3f`, edge `#8e5cd9`.

### 1.3 Component-local CSS variables (should move to global or be removed)

| File | Variables |
|---|---|
| `shared/components/cofirm-dialog/confirmation-dialog.component.scss:2-9` | `--color-primary`, `--color-primary-hover`, `--color-danger`, `--color-danger-hover`, `--color-text`, `--color-text-subtle` + **overrides** `--color-nodes-sidepanel-bg: #1e1e1e` locally |
| `features/configure-models/.../configure-models-dialog.component.scss:2-3` | `--configure-models-dialog-active-color: #d9d9de`, `--configure-models-dialog-inactive-color: #685fff` (naming inverted vs meaning — "inactive" is brand purple) |
| `visual-programming/flow-graph/flow-graph.component.scss:457-488` | `--arrange-icon-left/right` (hardcoded text colors) |
| `features/flows/.../global-sessions-list.component.scss:324` | locally **overrides** global `--color-nodes-background` |

### 1.4 Duplicated local SCSS `$` palettes (copy-paste)

The same palette block is pasted into at least 8 files
(`llm-popup`, `llm-item`, `tools-popup`, `tool-item`, `python-tool-item`,
`mcp-tool-item`, `agent-popup`, + variants in `tasks-table`, `agents-table`):

```scss
$bg-dark: #121212; $bg-card: #1e1e1e; $bg-input: #2d2d2d; $bg-item: #2a2a2a;
$bg-item-hover: #333333; $accent-blue: #4f46e5; $accent-hover: #6366f1;
$text-primary: #f5f5f5; $text-secondary: #a0a0a0; $text-tertiary: #777777;
$border-color: rgba(255,255,255,0.1); $status-green: #22c55e; $status-red: #ef4444;
```

`tasks-table` / `agents-table` use a *different* accent `$accent-blue: #6562f5`.
Neither `#4f46e5` nor `#6562f5` equals the brand `#685fff` — three near-identical
purples coexist (almost certainly unintended divergence).

`tool-config-form.component.scss:2-18` re-declares the **entire gray scale** as
SCSS `$gray-*` — exact duplicate of the global `--gray-*` custom properties.

---

## 2. Duplicate Value Groups (merge vs keep-separate)

Legend: **P** = unify at primitive level, keep semantic names separate.
**M** = true duplicates, merge into one semantic token.

### G1 — Brand purple `#685fff` (144 hardcoded + 5 variables) — **P**
Roles pointing at the same value: `--accent-color`, `--purple-primary`,
`--color-ks-button-activated`, `--color-ks-status-completed`,
`--configure-models-dialog-inactive-color`, local `--color-primary`.
→ One primitive `--purple-500`. Semantic roles stay separate:
`interactive accent` ≠ `status completed` ≠ `ks button` (per requirement:
changing status color must not recolor buttons).
`--purple-primary` and local `--color-primary` are aliases of the accent
role with no distinct meaning → **M** into `--accent-color`.

### G2 — Primary text `#d9d9de` / `rgba(217,217,222,1)` — **M + P**
`--color-text-primary`, `--text`, `--color-ks-text`,
`--configure-models-dialog-active-color` all render primary text.
`--text` is a pure alias → **M**. `--color-ks-text` is scoped to a feature but
semantically identical body text → **M** (flagged in §6 for confirmation).

### G3 — Secondary text `rgba(217,217,222,0.6)` (46 hardcoded) — **M**
`--text-secondary-60` = `--color-ks-transparent-text-60`. Note
`--color-text-secondary` uses a *different* base (`#c8ceda99` ≈ 60% of #c8ceda) —
visually near-identical but not equal. → consolidate on one secondary-text
primitive (decision needed: `#c8ceda99` vs `rgba(217,217,222,.6)`).

### G4 — Surface `#222225` — **P**
`--color-sidenav-background`, `--color-modals-background`,
`--color-nodes-actionbar-bg`, `--color-nodes-sidepanel-bg`.
Distinct roles (user may want modal ≠ sidenav) → keep 4 semantic tokens,
all → primitive `--graphite-850`.

### G5 — Surface `#27272b` — **P**
`--color-input-background`, `--color-secondary-btn-background`,
`--color-nodes-background`. Explicitly different roles → primitive `--graphite-800`.

### G6 — Surface `#212325` — **P**
`--color-background-body`, `--color-ks-background` → primitive `--graphite-900`.

### G7 — Border `#c8ceda24` — **P (critical)**
`--color-input-border` vs `--color-divider-regular`. Per requirement these must
never merge semantically (input borders ≠ dividers) → both point to primitive
`--steel-alpha-14`.

### G8 — Border `#c8ceda14` — **P**
`--color-divider-subtle` vs `--color-nodes-actionbar-border` → primitive
`--steel-alpha-8`.

### G9 — Accent purple washes `rgba(104,95,255,…)` — **P**
`.08` = `--color-ghost-btn-hover` = `--color-ks-transparent-purple`(.06 close) ;
`.15` = `--color-ghost-btn-active`; `.4` = `--inactive-purple`.
Plus 60+ hardcoded occurrences at 14 different alphas (.05–.9).
→ primitive alpha ladder `--purple-alpha-{5,8,10,15,20,30,40,50,80}`.

### G10 — Reds (error family) — **needs consolidation decision**
Currently in use: `#f54242` (`--color-error`), `#dc5b60` (`--color-ks-status-failed`),
`#f44336`/`#d32f2f` (confirm dialog), `#ef4444` (15×), `#ff4d4f` (7×),
`#dc3545`, `#ff6b6b`, `#ff4444`, `#e53935`, `#ff5252`, `#f87171`, `#dc2626`…
**14+ distinct reds** for essentially 2 roles (error/danger, status-failed).
→ propose red primitive scale (`--red-400/500/600`) and map all to
`--color-error` / `--color-status-failed` / `--btn-danger-*`. Exact target
values need a design decision (§6).

### G11 — Local popup purples `#4f46e5`, `#6366f1`, `#6562f5` — **needs decision**
Copy-paste palettes (§1.4). Almost certainly should become `--accent-color` /
`--accent-color-hover`. Flagged because it is a visible color change (§6).

### G12 — Status colors — **P**
`--color-ks-status-new #2aba6b` ↔ `--transparent-green-8 rgba(42,186,107,.08)` ↔
`$status-green #22c55e` (different green!);
`--color-ks-status-processing #ff8f3f` ↔ `--transparent-orange-8`;
`--color-ks-status-warning #ffcf00` ↔ hardcoded `rgba(255,207,0,…)`.
→ green/orange/yellow primitives + status semantic tokens; washes become
alpha variants of the same primitives (guarantees badge bg always matches badge text).

### G13 — VP selection `rgba(142,150,170,0.14)` — **M**
`--vp-connection-selection-color` = `--vp-selected-node-background-color` =
`--vp-hover-node-background-color`: same "selection wash" role → one token
(or keep hover/selected separate but point to one primitive — recommended).

### G14 — VP blues `#5672cd` / `#3e63dd` — **P**
`--vp-connection-for-create-path`, `--vp-selected-connection-color`,
`--vp-selected-node-border-color`, `--project-node-accent-color`, `--db-primary-1`
→ primitive `--blue-500`/`--blue-600`; roles stay separate.

### G15 — Gray scale duplication — **M**
Global `--gray-*` vs SCSS `$gray-*` in `tool-config-form.component.scss` — exact
value duplicates → delete SCSS copy, use custom properties.

---

## 3. Hardcoded Colors (no variable at all)

**194 component `.scss` files** contain raw colors. Top offenders:

| File | Count |
|---|---|
| `visual-programming/flow-graph/flow-graph.component.scss` | 51 |
| `pages/running-graph/components/graph-messages/graph-messages.component.scss` | 50 |
| `open-project-page/tasks-section/.../advanced-task-settings-dialog.component.scss` | 45 |
| `open-project-page/settings-section/settings-section.component.scss` | 41 |
| `features/flows/components/import-result-dialog/import-result-dialog.component.scss` | 36 |
| `pages/staff-page/components/agents-table/agents-table.component.scss` | 32 |
| `pages/chats-page/.../realtime-settings-dialog.component.scss` | 32 |
| `open-project-page/tasks-section/tasks-table/tasks-table.component.scss` | 31 |
| `features/flows/components/version-history-panel/version-history-panel.component.scss` | 30 |
| `features/files/components/add-to-flow-dialog/add-to-flow-dialog.component.scss` | 29 |
| …and 184 more files | 1–28 each |

Most frequent hardcoded values → replacement targets:

| Value | Count | Target token |
|---|---|---|
| `#685fff` | 144 | `--accent-color` (or role-specific semantic) |
| `#fff` / `#ffffff` | 123 | context-dependent: `--color-text-on-accent`, `--white` primitive |
| `rgba(255,255,255,0.1)` | 86 | `--white-alpha-10` (borders/hover washes) |
| `#d9d9de` | 54 | `--color-text-primary` |
| `#2b2d30` | 51 | `--color-flow-card-bg` |
| `rgba(217,217,222,0.6)` | 46 | `--color-text-secondary` |
| `rgba(0,0,0,0.3)` / `.15` / `.2` / `.4` | 99 | `--shadow-*` tokens |
| `#2a2a2a`, `#333`, `#1e1e1e`, `#2d2d2d` | 85+ | graphite surface primitives |
| `#212325` | 26 | `--color-background-body` |
| `#aaa`, `#888`, `#666`, `#999` | 50+ | gray text primitives |
| `#ef4444`, `#f44336`, `#ff4d4f`, … | 60+ | error/danger semantic tokens |
| `#5e9eff` | 15 | new `--blue-400` (info accent) |
| `#00bfa5` + 12 alpha variants | 26 | `--teal-500` + alpha ladder (flow links) |

---

## 4. Proposed Token Architecture

Two layers, defined in `src/styles/_variables.scss` (or split into
`_primitives.scss` + `_semantic.scss`). Both themes define the full set.

### 4.1 Primitive layer (raw palette — NOT used directly by components)

```scss
:root {
    // Brand purple
    --purple-300: #8c7fff;
    --purple-400: #7a70ff;
    --purple-500: #685fff;        // brand
    --purple-600: #574fd6;
    --purple-700: #473fb3;
    --purple-alpha-8:  rgba(104, 95, 255, 0.08);
    --purple-alpha-15: rgba(104, 95, 255, 0.15);
    --purple-alpha-40: rgba(104, 95, 255, 0.4);

    // Graphite (dark surfaces)
    --graphite-950: #1a1a1c;
    --graphite-900: #212325;      // body
    --graphite-850: #222225;      // sidenav/modal
    --graphite-800: #27272b;      // input/nodes
    --graphite-750: #2b2d30;      // flow card
    --graphite-700: #2c2c2e;      // ks-line
    --graphite-650: #3a3e48;      // hover row

    // Gray scale — keep existing --gray-50…950 as-is (already primitive)

    // Steel (cool text/border base #c8ceda + alpha)
    --steel-alpha-8:  #c8ceda14;
    --steel-alpha-14: #c8ceda24;
    --steel-alpha-30: #c8ceda4d;
    --steel-alpha-60: #c8ceda99;

    // Light text base #d9d9de + alpha ladder
    --fog-100: #ececf3;
    --fog-200: #d9d9de;
    --fog-alpha-80: rgba(217, 217, 222, 0.8);
    --fog-alpha-60: rgba(217, 217, 222, 0.6);
    --fog-alpha-20: rgba(217, 217, 222, 0.2);
    --fog-alpha-8:  rgba(217, 217, 222, 0.08);

    // White/black alpha (washes, shadows)
    --white: #ffffff;
    --white-alpha-3 … --white-alpha-20;
    --black-alpha-15 … --black-alpha-50;   // shadows

    // Status / feedback
    --green-500: #2aba6b;   --green-alpha-8: rgba(42,186,107,.08);
    --yellow-500: #ffcf00;  --yellow-alpha-8: rgba(255,207,0,.06);
    --orange-500: #ff8f3f;  --orange-alpha-8: rgba(255,143,63,.08);
    --red-400: #ff6b6b;
    --red-500: #f54242;     --red-alpha-8: rgba(245,66,66,.08);
    --red-600: #dc5b60;     // status-failed (decide: keep or fold into red-500)
    --sky-500: #48cbff;     --sky-alpha-8: rgba(72,203,255,.06);
    --teal-500: #00bfa5;    --teal-alpha-8: rgba(0,191,165,.08);
    --blue-400: #5e9eff;
    --blue-500: #5672cd;
    --blue-600: #3e63dd;
}
```

Light theme overrides primitives only where the ramp itself flips
(graphite → slate/white ramp: `#f8fafc`, `#ffffff`, `#f1f5f9`, `#e2e8f0`,
text ramps `#1e293b`/`#64748b`).

### 4.2 Semantic layer (what components — and the future settings page — use)

```scss
:root {
    // Interactive (user-customizable group: "Buttons & accents")
    --accent-color:            var(--purple-500);
    --accent-color-hover:      var(--purple-600);
    --accent-color-active:     var(--purple-700);
    --accent-disabled:         var(--purple-alpha-40);
    --btn-secondary-bg:        var(--graphite-800);
    --btn-secondary-bg-hover:  var(--white-alpha-9);
    --btn-ghost-hover:         var(--purple-alpha-8);
    --btn-ghost-active:        var(--purple-alpha-15);
    --btn-danger-bg:           var(--red-500);
    --btn-danger-bg-hover:     var(--red-600);

    // Inputs & selects (group: "Form controls")
    --input-bg:                var(--graphite-800);
    --input-border:            var(--steel-alpha-14);
    --input-placeholder:       var(--steel-alpha-30);
    --input-bg-hover:          var(--graphite-750);

    // Text (group: "Typography colors")
    --text-primary:            var(--fog-200);
    --text-secondary:          var(--steel-alpha-60);
    --text-primary-hover:      var(--fog-100);
    --text-on-accent:          var(--white);

    // Surfaces (group: "Backgrounds")
    --surface-body:            var(--graphite-900);
    --surface-sidenav:         var(--graphite-850);
    --surface-modal:           var(--graphite-850);
    --surface-card:            var(--graphite-750);
    --surface-overlay-scrim:   var(--black-alpha-30);

    // Borders vs dividers (separate groups by requirement)
    --border-card:             var(--white-alpha-3);
    --divider-regular:         var(--steel-alpha-14);
    --divider-subtle:          var(--steel-alpha-8);

    // Statuses (group: "Status colors" — independent from buttons)
    --status-info:             var(--sky-500);
    --status-completed:        var(--purple-500);
    --status-new:              var(--green-500);
    --status-warning:          var(--yellow-500);
    --status-processing:       var(--orange-500);
    --status-failed:           var(--red-600);
    --status-error:            var(--red-500);
    // + matching *-bg washes via alpha primitives (badge bg auto-follows)

    // Scrollbar, VP nodes, flow links — keep current names, repoint to primitives
}
```

Existing names (`--color-text-primary`, `--color-input-background`, …) can be
kept as-is and simply re-pointed to primitives to minimize migration churn —
renaming to the scheme above is optional (decision in §6).

### 4.3 Typography tokens

Current state: `'Inter', sans-serif` (13×), `Inter, sans-serif` (10×),
`'inter'` (1×, invalid-ish), `Roboto` in `_reset.scss:19` (base font of the whole
app is Roboto while components ask for Inter!), 6 different mono stacks;
35+ font sizes mixing px/rem/em; weights include invalid `130` (3×) and stray
`200`/`300`.

```scss
:root {
    --font-family-base: 'Inter', 'Roboto', 'Helvetica Neue', sans-serif;
    --font-family-mono: 'JetBrains Mono', 'Fira Code', Consolas, monospace;

    --font-size-2xs: 0.625rem;  // 10px
    --font-size-xs:  0.75rem;   // 12px
    --font-size-sm:  0.8125rem; // 13px
    --font-size-md:  0.875rem;  // 14px  ← dominant body size (328 uses)
    --font-size-lg:  1rem;      // 16px
    --font-size-xl:  1.125rem;  // 18px
    --font-size-2xl: 1.25rem;   // 20px
    --font-size-3xl: 1.5rem;    // 24px
    --font-size-4xl: 1.75rem;   // 28px

    --font-weight-regular:  400;
    --font-weight-medium:   500;   // dominant (218 uses)
    --font-weight-semibold: 600;
    --font-weight-bold:     700;

    --line-height-tight: 1.2;
    --line-height-base:  1.5;
}
```

Semantic roles: `--text-body` (md/regular), `--text-body-sm` (sm),
`--text-caption` (xs/secondary), `--text-label` (xs/medium),
`--text-button` (md/medium), `--text-heading-{1,2,3}` (3xl/2xl/xl semibold),
`--text-code` (mono/sm). Odd sizes (11px, 15px, 0.9rem, 0.85rem, 1.1rem, 8px…)
snap to the nearest step during migration.

---

## 5. Migration Map (summary)

| Old | New | Type |
|---|---|---|
| `--purple-primary`, local `--color-primary` | `--accent-color` | merge (alias) |
| `--text` | `--color-text-primary` | merge (alias) |
| `--text-secondary-60`, `--color-ks-transparent-text-60` | `--color-text-secondary` | merge (needs G3 value decision) |
| `--color-ks-text` | `--color-text-primary` | merge (confirm) |
| `--color-ks-button-activated` | keep, repoint → `--purple-500` | primitive unify |
| `--color-ks-status-*` | `--status-*` | rename + repoint |
| `--configure-models-dialog-*` | global text/accent tokens | delete local |
| confirm-dialog local `--color-danger*` | `--btn-danger-*` | promote to global |
| copy-pasted `$bg-*`/`$accent-blue`/`$text-*` palettes (8+ files) | semantic tokens | delete SCSS vars |
| `$gray-*` in tool-config-form | `--gray-*` | delete duplicate scale |
| 194 files × hardcoded values | per §3 table | replace |
| `font-family: 'Inter'…` ×26 variants | `--font-family-base` / `--font-family-mono` | replace |
| `font-size`/`font-weight` raw values | `--font-size-*` / `--font-weight-*` | replace, snap to scale |

---

## 6. Gaps & Risks — RESOLVED (owner decisions recorded)

1. `var(--white)` undefined (21 uses, no fallback) → **define `--white: #ffffff`**.
2. `--gray-050` typo (4 uses) → **fix to `--gray-50`**.
3. Duplicate `--db-primary-1` in VP variables → **keep the overriding value `#5672cd`**,
   delete the `#3e63dd` line.
4. Roboto in `_reset.scss` vs Inter in components → **Inter is the base font**
   (`--font-family-base: 'Inter', …`).
5. `font-weight: 130` (3×) → **replace with 300**.
6. Incomplete light theme → **no theme switcher in use; fill missing light values
   with any reasonable equivalents** (slate/white ramp), correctness not critical.
7. Theme convention conflict (global vs VP) → **unify**: `:root` = dark,
   `.my-app-light` = light everywhere; migrate VP `.dark` convention.
8. Secondary text base → **`rgba(217, 217, 222, 0.6)`** (drop `#c8ceda99` base).
9. Red consolidation → **`--red-500: #f54242`** is the canonical error/danger red;
   `--red-600: #dc5b60` stays for status-failed; all other reds migrate onto them.
10. Popup palettes `#4f46e5`/`#6366f1`/`#6562f5` → **merge into brand accent**
    (`--accent-color` / `--accent-color-hover`) as proposed.
11. `--color-ks-*` scoping → **merge into global tokens** (surfaces/text/line into
    global semantics; ks statuses become `--status-*`).
12. Local overrides of global tokens → **forbidden**: components must not override
    global variables; introduce proper semantic variables instead
    (`confirmation-dialog`, `global-sessions-list` to be fixed).
13. Naming → **keep existing public names** (`--color-text-primary`, etc.);
    add new tokens only for currently-hardcoded roles.
14. `rgba(var(--purple-rgb))` undefined → **map to the closest semantic color**
    (accent purple alpha primitives).

---

## 7. Customization Readiness (future settings page groups)

| UI group | Semantic tokens | Independent? |
|---|---|---|
| Accent & buttons | `--accent-color(±hover/active)`, `--btn-secondary-*`, `--btn-ghost-*`, `--btn-danger-*` | yes |
| Form controls | `--input-bg/border/placeholder` | yes — borders separate from dividers |
| Text | `--text-primary/secondary/on-accent` | yes |
| Backgrounds | `--surface-body/sidenav/modal/card` | yes — 4 separately tunable surfaces |
| Dividers & borders | `--divider-regular/subtle`, `--border-card` | yes — never coupled to input borders |
| Statuses | `--status-{info,new,warning,processing,failed,completed,error}` + auto `-bg` washes | yes — changing a status never touches buttons |
| Flow editor | `--vp-*`, node accent colors | yes (own namespace) |
| Typography | `--font-family-base/mono`, size & weight scales | yes |

Prerequisites before building the page: fix §6 bugs, complete the light theme,
eliminate the 194-file hardcode debt (else user changes won't apply everywhere).

---

*Generated by automated audit. Source data: ripgrep sweeps of `frontend/src/{app,styles}/**/*.scss|html|ts` (colors: hex/rgb(a)/hsl(a) patterns; variables: definitions vs `var()` usages; typography: font-* declarations).*
