# Frontend npm audit Remediation (EST-3802)

Purpose: evidence that the frontend dependency findings raised by the security audit are
closed. The audit's frontend items were an end-of-life Angular runtime (B‑01) and 48
advisories in the build toolchain (H‑05). Both are addressed by moving off Angular 19 and
regenerating the dependency tree.

Scope is the `frontend/` workspace only. Backend and Python lockfiles are tracked
separately.

Raw `npm audit --json` output for both states, the full advisory inventory and the
before/after version table are in [`evidence/frontend-angular-22/`](./evidence/frontend-angular-22/).
The numbers below are reproducible from those files.

---

## Result

|                                            | before                                       | after |
| ------------------------------------------ | -------------------------------------------- | ----- |
| `npm audit` findings (packages)            | 77 — 3 critical, 44 high, 29 moderate, 1 low | **0** |
| distinct advisories (GHSA)                 | **114**                                      | **0** |
| findings in the production tree            | 29 — 1 critical, 18 high, 10 moderate        | **0** |
| packages in the lockfile                   | 1 398                                        | 839   |
| highest severity reaching first-party code | CVSS **9.0** (`GHSA-g93w-mfhg-p222`)         | —     |

`npm audit` groups findings by package, so its headline count understates the problem:
77 affected packages carried 114 distinct advisories. Of those, 53 sat in the production
dependency tree and 61 were build-time only.

Two caveats, stated so the numbers are not read as stronger than they are. First,
"production tree" is npm's classification, not bundle reachability — `lodash` (8.1) and
`svgo` (8.2) were pulled by `@tabler/icons-webfont`, whose build scripts are never imported
by application code. Second, the highest CVSS in the whole set was `GHSA-wf6x-7x77-mvgw`
(Immutable prototype pollution, 9.8), which arrived through `sass` and is build-time only.
The single highest-severity advisory that genuinely reached shipped code was the Angular
one at 9.0.

## Commits

|             |                                                                       |
| ----------- | --------------------------------------------------------------------- |
| `d7338534d` | dependency cleanup, Angular untouched — 77 → 28 findings, prod 29 → 9 |
| `fe36ca19e` | Angular 19 → 22 — 28 → 0, prod 9 → 0                                  |

Splitting the work this way isolates the two causes. The first commit shows how much of the
backlog was tree drift rather than framework age: regenerating the lockfile and removing the
unused webpack toolchain accounted for 49 of the 77 findings without touching a line of
application code.

## Angular: what the project was actually exposed to

Counting by advisory rather than by package, because every 19.2.x release reports the same
three affected packages (`common`, `compiler`, `core`) and the difference is only visible
inside them:

| version                                         | advisories | highest      |
| ----------------------------------------------- | ---------- | ------------ |
| 19.2.18 — what `main` ran                       | 12         | **CVSS 9.0** |
| 19.2.25 — final v19 release, no further patches | 6          | 7.5          |
| 22.1.2 — current                                | **0**      | —            |

Six of the twelve had been fixed inside the v19 line and simply not taken; `main` was seven
patches behind the final release. Among the six was `GHSA-g93w-mfhg-p222` (CVSS 9.0,
sanitiser bypass via `i18n-` attribute bindings), fixed in 19.2.20.

The remaining six have no fixed version in v19 at all, which is why a patch bump was never
a sufficient answer. Their reachability in this codebase, verified by inspection:

| advisory                                                    | CVSS | reachable | basis                                                                                                                                     |
| ----------------------------------------------------------- | ---- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `GHSA-58w9-8g37-x9v5` two-way binding sanitisation bypass   | 6.1  | **yes**   | 52 files use `[(…)]`, 35 of them `[(ngModel)]`                                                                                            |
| `GHSA-48r7-hpm6-gfxm` `formatDate` OOM DoS                  | 7.5  | no        | `formatDate` is never imported from `@angular/common`; the 9 matches in `src/` are the project's own local methods. No `digitsInfo` usage |
| `GHSA-rgjc-h3x7-9mwg` hydration DOM clobbering              | 6.1  | no        | no `provideClientHydration`; client-rendered only                                                                                         |
| `GHSA-39pv-4j6c-2g6v` HttpTransferCache weak cache key      | 6.1  | no        | transfer cache not enabled                                                                                                                |
| `GHSA-jhpw-976m-542j` HttpTransferCache key ambiguity       | —    | no        | as above                                                                                                                                  |
| `GHSA-jj27-h5hq-8x99` i18n XSS via event-handler attributes | —    | no        | no `i18n` attributes in any template                                                                                                      |

Five of six were unreachable and one was reachable. This is context, not mitigation: the
protection rested on nobody adding an `i18n` attribute or enabling hydration, and it does
not satisfy an end-of-life-software control either way.

## Dependency changes

23 direct dependencies changed version, 6 were added, 9 removed. Full table with declared
and resolved versions for both states: `evidence/frontend-angular-22/direct-dependencies.tsv`.

The substantive moves:

- Angular framework 19.2.18 → 22.1.2, Material and CDK 19.2.19 → 22.1.3, CLI and build
  19.2.20 → 22.1.4, TypeScript 5.5.4 → 6.0.3.
- `@angular-devkit/build-angular` removed. `angular.json` already built through
  `@angular/build:application`, so the webpack toolchain — `webpack-dev-server`,
  `http-proxy-middleware`, `less`, `image-size`, `serialize-javascript`, `piscina` — was
  dead weight carrying advisories. `@angular/build` is now declared directly.
- `@angular/platform-browser-dynamic` removed; `main.ts` bootstraps through
  `bootstrapApplication`.
- `@tabler/icons-webfont` moved to `devDependencies`. Only its prebuilt CSS and woff2 are
  consumed, while the package itself pulls `svgo`, `tar` and `undici`.
- Karma replaced by `@angular/build:unit-test` on Vitest, a builder that exists only from
  v22. Karma is deprecated upstream and `karma.conf.js` here was entirely commented out.
- `jsonc-parser` and `@types/json-schema` newly declared. Both are imported by `src/` but
  were absent from `package.json`, resolving only through transitive devDependencies — so
  shipped code depended on dev-only packages, and removing the webpack tree broke the
  build until they were declared.
- Six caret ranges that reach the browser — the two `@fontsource` packages, `papaparse`,
  `read-excel-file`, `@tabler/icons-webfont` and `prettier` — pinned to the versions `main`
  already resolved, so regenerating the lockfile did not silently move them. Their resolved
  versions are unchanged; only the declarations differ.

Four `overrides` entries are required and cannot be removed. The first was needed by the
upgrade itself: `monaco-editor` pins `dompurify@3.2.7`, which is vulnerable, and moving monaco
to 0.56.0 does not help because it pins 3.4.8. The override forces `^3.4.14`.

The other three were added later, when `main` was merged back into the branch — see
Advisories published after the measurement.

## Advisories published after the measurement

The zero above is a measurement against the advisory database as it stood on 2026-08-19, not a
permanent property of the tree. Reinstalling on 2026-09-04, with the lockfile unchanged,
returned three findings: one high and two moderate. Nothing in the dependency tree had moved,
so these are advisories published in the intervening two weeks against versions the branch
already resolved. This is the drift the CI `npm audit` gate exists to surface, and it surfaced
on the first run after the merge rather than at review.

| package                 | severity                      | reaches        | arrives through                                          |
| ----------------------- | ----------------------------- | -------------- | -------------------------------------------------------- |
| `fast-uri` 3.1.5        | high — 4 advisories, CVSS 7.5 | build only     | `@angular/cli` → `@angular-devkit/core` → `ajv`          |
| `qs` 6.15.3             | moderate — 2 advisories       | build only     | `@angular/cli` → `@modelcontextprotocol/sdk` → `express` |
| `@xmldom/xmldom` 0.9.11 | moderate                      | **production** | `read-excel-file`                                        |

Only the third reached shipped code, and it is a genuine runtime import rather than an npm
classification artefact: `storage-preview.component.ts` imports `read-excel-file/browser` to
render the spreadsheet preview.

None of the three could be closed by moving a direct dependency, because all three are
transitive and their parents pin the vulnerable ranges — the same shape as the `dompurify`
case. So they are closed the same way:

```json
"overrides": {
    "dompurify": "^3.4.14",
    "@xmldom/xmldom": "^0.9.12",
    "fast-uri": "^4.1.4",
    "qs": "^6.16.0"
}
```

`@xmldom/xmldom` and `qs` are in-range moves. `fast-uri` is not: 3.1.5 → 4.1.4 forces a major
inside `ajv`, so it was resolved in a scratch copy of `package.json` and `package-lock.json`
first, confirming both that the tree resolves and that the result is `found 0 vulnerabilities`,
before being applied to the workspace. `package.json` changed in `overrides` only; the whole
lockfile delta is these three packages resolving up, plus a duplicate `chokidar@3` subtree
under `svgtofont` that deduped away on reinstall.

After: `npm audit` and `npm audit --omit=dev` both report 0, at 839 packages total and 58 in
the production tree. `THIRD-PARTY-NOTICES.md` was regenerated, as the notices gate demanded on
the changed lockfile.

Read these three as evidence about process rather than about this branch: a dependency tree
that audits clean today can audit dirty next week without anyone touching it, which is why the
durable control is the gate in CI and not the number in this document.

## Deliberately unchanged

At the time of the upgrade `@foblex/flow` stayed at 18.4.0 and `ag-grid` at 33.3.2. Both
satisfied Angular 22 peer ranges unchanged (`>=17.3.0` and `>=17.0.0`) and neither carried an
advisory, so there was no security reason to move them. The coupling is one-directional —
ag-grid 36 requires Angular ≥ 20, but Angular 22 does not require ag-grid 36 — and putting
three grid majors in the same commit as the framework upgrade would have made a regression
impossible to attribute. Both have since been taken as separate steps, described below.

## Deferred at the time of the upgrade, none of it required by it

Recorded as it stood when the upgrade landed. All three are now closed; the detail is in the
next section.

- The control flow migration (`*ngIf` → `@if`, ~73 files, plus 262 now-redundant
  `standalone: true`). The schematic is marked `optional: true` and `NgIf` / `NgForOf` are
  still exported from `@angular/common@22.1.2`.
- The `$safeNavigationMigration()` shims left in six templates by the v22 safe-navigation
  change. Removing them is per-site work: it is only safe where the consumer does not
  distinguish `null` from `undefined`.
- The two extended diagnostics the migration suppressed in `tsconfig.app.json` and
  `tsconfig.spec.json` (`nullishCoalescingNotNullable`, `optionalChainNotNullable`).

## Closed since

Items listed as deferred above that have since been done, on the same story: the control flow
migration; the `$safeNavigationMigration()` shim, together with the two extended diagnostics it
had needed suppressed; `provideMarkdown()` and `provideMonacoEditor()` in place of the
deprecated module providers; `zone.js` 0.16.2; 13 debug `console.log` calls, now held out by an
eslint rule; and `ngx-json-viewer`, replaced by a vendored component under
`shared/components/json-viewer/`, so the unmaintained dependency is gone rather than merely
flagged. Its MIT attribution is recorded in the Vendored code section of
THIRD-PARTY-NOTICES.md.

`@angular/animations` is also gone, which the deferred list above had scoped as state-machine
work. Reading the nine files rather than counting their calls showed why it was smaller than it
looked: of nine triggers, five were dead — two defined and never bound, two registered as
component metadata with no binding, and one duplicating an opacity transition the component's
own stylesheet already ran at the same 300ms. Of the four live ones, three were plain
enter/leave and became `animate.enter` / `animate.leave` with CSS keyframes; the fourth,
`expandCollapse`, was a boolean class toggle at 44 call sites needing no framework at all.
Those became one `grid-collapsible` class using `grid-template-rows: 0fr → 1fr`, chosen over
`interpolate-size: allow-keywords` because the repository declares no browserslist and the
default Angular targets include Firefox. Per-site timings are preserved through
`--collapse-duration` / `--collapse-easing`. The trick needs a single grid child, so seven
sites with two or more children gained a wrapper; a script verified all 46 sites end with
exactly one. This also removes the shared trigger's `max-height: 1000px` ceiling, above which
content used to spill, and drops the 64 kB animations chunk that `provideAnimationsAsync()` had
been fetching lazily. Material and CDK read `ANIMATION_MODULE_TYPE` with `{ optional: true }`
and compare it against `'NoopAnimations'`, so removing the provider leaves their own animations
enabled.

Three defects the animations work surfaced are also closed. `.details-content` in
`staff-agent-card` capped at `max-height: 800px` with `overflow: hidden`, silently clipping
agents with many tools; it now uses `grid-collapsible` like the rest. Its own
`transition: margin-top` would have overridden the grid transition shorthand — the same
specificity trap as `.entity-items`, since component styles carry an encapsulation attribute
and outrank a global class — so the offset moved to `padding-top` on the wrapper, where it is
part of the animated height. `expand-panel` was exported from the shared barrel and referenced
nowhere; deleted.

The third turned out to be worth more than the defect. A `bottom-left` toast entered and left
to the right, inherited from the old trigger where every `bottom-*` position shared one X
keyframe. Fixing the direction led to checking whether it was reachable: `ToastPosition`
offered six positions, but only three containers were mounted, and of those `top-center`
received nothing, because across 247 toast calls in 57 files only two values are ever passed —
`bottom-right` (also the default) and `top-right`. So four of six positions could not render at
all, and passing one would have dropped the toast silently with no error, since every mounted
container filters by its own position. The type is now narrowed to the two positions that
exist, which turns that silent loss into a compile error; the unused container and the dead
positional CSS are gone with it.

`ag-grid` 33.3.2 → 36.1.0 is also done, three majors in one step. Nothing in the API surface
broke: 33 imported symbols across 19 components implementing ag-grid interfaces compiled with
zero errors and zero warnings, because the painful v33 migration — module repackaging and the
Theming API — was already in place. The theming parameters are provably still valid rather than
assumed: `withParams` is typed `Partial<TParams>` and the call sites are object literals, so
excess property checking would have failed the build on any renamed parameter.

The cost was in the DOM instead, where no compiler could see it. v36 restructured the internal
markup — 51 classes removed, 467 added, largely re-prefixed `ag-grid-` — and we styled 42 of
them across 165 occurrences. A script comparing our references against both versions found four
casualties, and separated them from two false alarms: `ag-grid-wrap` is our own class, and one
pair sat inside a commented-out block. Of the four, three were CSS that would have silently
stopped applying; half of those turned out never to have applied anyway, because
`.ag-layout-auto-height` only exists when `domLayout: 'autoHeight'` is set and only one of the
four grids sets it. The `min-height` hacks they contained worked around a v33 defect that v36
fixed, confirmed by eye on the empty grids, so they were deleted rather than remapped.

The fourth was the one that mattered: `.ag-body-viewport` was read through a runtime
`querySelector`, and on `null` the code correctly took an early return that set the overlay list
to empty. The result would have been the column-group collapse chevrons in the classification
decision table quietly disappearing — no crash, no console output, a feature simply absent. The
replacement is `.ag-grid-viewport`, chosen structurally (`ref: "eGridViewport"`, direct child of
`ag-root`) and then confirmed by scrolling a grouped grid, since the code depends on that
element's `scrollTop`.

Two smaller results: the frozen-column separator moved off an `!important` override of internal
class names onto the supported `pinnedColumnBorder` theme parameter, which existed in v33 too
and so could always have been done properly; and v36 added a `colDef` check that warns when it
has inferred `cellDataType: 'object'` and is falling back to the default object formatter —
answered with `cellDataType: false` on the four columns that hold objects or arrays and render
through their own `cellRenderer`.

`@foblex/flow` 18.4.0 → 19.1.6 closes the backlog, and needed no source changes at all. The
major number does not mark a break here: comparing the two versions directly, all sixteen
symbols we import are still exported, the three connection-builder interfaces and
`ICurrentSelection` are byte-identical, all thirty internal CSS classes we style still exist,
and the fesm bundle is the same size with the same export count. Reflow, accessibility, the
layout engine and the `FF1xxx` dev diagnostics were already present in 18.4.0, so v19 brings no
new machinery and no new console output. The library numbers majors as release trains rather
than by compatibility — v18 shipped in January 2026, v19 in July — and it is actively
maintained, with 19.1.6 published three weeks before the bump. Only `@foblex/flow` moved: the
four sibling packages were already current, and v19 loosened their peer ranges from exact pins
to carets. The bump also picked up seven releases we were behind inside our own major.

A clean build proves much less here than it did for ag-grid, because this library is drag,
connect and zoom geometry, which no compiler inspects. It was verified by hand in the flow
editor, with attention to the three places our code sits on top of theirs: the custom
`IFConnectionBuilder`, the backward-arc path builder with segment avoidance, and connection
waypoints.

`withXhr()` is gone too, so `HttpClient` now runs on the fetch backend Angular 22 defaults to.
This was deliberately held back from the upgrade rather than deferred indefinitely: the five
`withCredentials: true` calls it affects are all on the auth path — login, logout, refresh,
first-setup, password-change — and they are exercised cross-origin, which is exactly where
fetch's `credentials: 'include'` and XHR's `withCredentials` diverge over preflight,
`Access-Control-Allow-Credentials` and cookie `SameSite`. Inside the upgrade commit, a broken
login would have had thirteen candidate causes.

The one thing the fetch backend genuinely cannot do is report upload progress, and the codebase
has no `reportProgress`, no `HttpEventType` and no `observe: 'events'` anywhere, so that risk
was absent from the start. Interceptors sit above the backend and are unaffected;
`authInterceptor` only reads `err.status`, which Angular normalises identically on both. Checked
by hand afterwards: login, a forced 401 with token refresh and retry, logout, password change,
file upload and blob download.

---

## Method

Both states were audited against the same advisory database snapshot on 2026-08-19, so the
counts are directly comparable. The "before" state is `frontend/package.json` and
`frontend/package-lock.json` at `c2472d77b`, restored into a scratch directory and audited
there; the "after" state is the branch as it stands.

To reproduce:

```sh
# before
git show c2472d77b:frontend/package.json      > /tmp/before/package.json
git show c2472d77b:frontend/package-lock.json > /tmp/before/package-lock.json
cd /tmp/before && npm audit --json

# after
cd frontend && npm audit --json && npm audit --omit=dev --json
```

Verification on the branch: `npm audit` 0 findings in both the full and production-only
trees, `npm run lint`, `ng test` and `ng build --configuration production` all pass, and a
manual smoke pass over login, the flow editor, ag-grid, monaco, markdown rendering and the
realtime dialogs.

Note on tooling coverage: `npm run lint` is `eslint src` and does not check formatting —
prettier is a separate command. That gap is now closed in CI. The `frontend-checks` job in
`.github/workflows/pr.yml` runs six gates: `npm run lint`, `npm run format:check`,
`scripts/check-undeclared-imports.mjs`, `scripts/check-third-party-notices.mjs`, `npm test`
and `npm audit --audit-level=high`.

One control is still outside the repository and still open: `frontend-checks` is not yet a
required status check in branch protection, so a pull request can be merged without it having
passed. Setting it requires admin rights on the ruleset.

## Files

| file                                                   | contents                                                                       |
| ------------------------------------------------------ | ------------------------------------------------------------------------------ |
| `evidence/frontend-angular-22/audit-before-all.json`   | full `npm audit --json` at `c2472d77b`                                         |
| `evidence/frontend-angular-22/audit-before-prod.json`  | same with `--omit=dev`                                                         |
| `evidence/frontend-angular-22/audit-after-all.json`    | full `npm audit --json` on the branch                                          |
| `evidence/frontend-angular-22/audit-after-prod.json`   | same with `--omit=dev`                                                         |
| `evidence/frontend-angular-22/advisories-before.tsv`   | all 114 advisories with severity, CVSS and whether each is still present after |
| `evidence/frontend-angular-22/direct-dependencies.tsv` | every direct dependency, declared and resolved, before and after               |
