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

| | before | after |
| --- | --- | --- |
| `npm audit` findings (packages) | 77 — 3 critical, 44 high, 29 moderate, 1 low | **0** |
| distinct advisories (GHSA) | **114** | **0** |
| findings in the production tree | 29 — 1 critical, 18 high, 10 moderate | **0** |
| packages in the lockfile | 1 398 | 843 |
| highest severity reaching first-party code | CVSS **9.0** (`GHSA-g93w-mfhg-p222`) | — |

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

| | |
| --- | --- |
| `d7338534d` | dependency cleanup, Angular untouched — 77 → 28 findings, prod 29 → 9 |
| `fe36ca19e` | Angular 19 → 22 — 28 → 0, prod 9 → 0 |

Splitting the work this way isolates the two causes. The first commit shows how much of the
backlog was tree drift rather than framework age: regenerating the lockfile and removing the
unused webpack toolchain accounted for 49 of the 77 findings without touching a line of
application code.

## Angular: what the project was actually exposed to

Counting by advisory rather than by package, because every 19.2.x release reports the same
three affected packages (`common`, `compiler`, `core`) and the difference is only visible
inside them:

| version | advisories | highest |
| --- | --- | --- |
| 19.2.18 — what `main` ran | 12 | **CVSS 9.0** |
| 19.2.25 — final v19 release, no further patches | 6 | 7.5 |
| 22.1.2 — current | **0** | — |

Six of the twelve had been fixed inside the v19 line and simply not taken; `main` was seven
patches behind the final release. Among the six was `GHSA-g93w-mfhg-p222` (CVSS 9.0,
sanitiser bypass via `i18n-` attribute bindings), fixed in 19.2.20.

The remaining six have no fixed version in v19 at all, which is why a patch bump was never
a sufficient answer. Their reachability in this codebase, verified by inspection:

| advisory | CVSS | reachable | basis |
| --- | --- | --- | --- |
| `GHSA-58w9-8g37-x9v5` two-way binding sanitisation bypass | 6.1 | **yes** | 52 files use `[(…)]`, 35 of them `[(ngModel)]` |
| `GHSA-48r7-hpm6-gfxm` `formatDate` OOM DoS | 7.5 | no | `formatDate` is never imported from `@angular/common`; the 9 matches in `src/` are the project's own local methods. No `digitsInfo` usage |
| `GHSA-rgjc-h3x7-9mwg` hydration DOM clobbering | 6.1 | no | no `provideClientHydration`; client-rendered only |
| `GHSA-39pv-4j6c-2g6v` HttpTransferCache weak cache key | 6.1 | no | transfer cache not enabled |
| `GHSA-jhpw-976m-542j` HttpTransferCache key ambiguity | — | no | as above |
| `GHSA-jj27-h5hq-8x99` i18n XSS via event-handler attributes | — | no | no `i18n` attributes in any template |

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

One `overrides` entry is required and cannot be removed: `monaco-editor` pins
`dompurify@3.2.7`, which is vulnerable, and moving monaco to 0.56.0 does not help because
it pins 3.4.8. The override forces `^3.4.14`.

## Deliberately unchanged

`@foblex/flow` stays at 18.4.0 and `ag-grid-angular` / `ag-grid-community` at 33.3.2. Both
satisfy Angular 22 peer ranges unchanged (`>=17.3.0` and `>=17.0.0`) and neither carries an
advisory, so there is no security reason to move them. The coupling is one-directional —
ag-grid 36 requires Angular ≥ 20, but Angular 22 does not require ag-grid 36 — and putting
three grid majors in the same commit as the framework upgrade would make a regression
impossible to attribute. Both are queued as follow-ups.

## Deferred, none of it required by the upgrade

- The control flow migration (`*ngIf` → `@if`, ~73 files, plus 262 now-redundant
  `standalone: true`). The schematic is marked `optional: true` and `NgIf` / `NgForOf` are
  still exported from `@angular/common@22.1.2`.
- The `$safeNavigationMigration()` shims left in six templates by the v22 safe-navigation
  change. Removing them is per-site work: it is only safe where the consumer does not
  distinguish `null` from `undefined`.
- The two extended diagnostics the migration suppressed in `tsconfig.app.json` and
  `tsconfig.spec.json` (`nullishCoalescingNotNullable`, `optionalChainNotNullable`).
- `withXhr()` in `app.config.ts`. Angular 22 switched the default `HttpClient` backend to
  fetch; the migration added `withXhr()` to preserve behaviour. It should not be removed
  casually — four interceptors and cookie handling depend on the backend.
- `@foblex/flow` 18.4.0 → 19.1.6 and `ag-grid` 33.3.2 → 36.1.0, both awaiting a team decision.
- Two pre-existing defects surfaced while removing `@angular/animations`, both left alone
  because fixing them changes appearance and neither is a dependency concern: the toast
  container animates every `bottom-*` position along X with `translateX(100%)`, so a
  `bottom-left` toast enters and leaves to the right; and `.details-content` in
  `staff-agent-card` caps at `max-height: 800px` with `overflow: hidden`, silently clipping
  taller content.

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
prettier is a separate command. A `prettier --check` gate, plus a scan of bare imports in
`src/` against `package.json`, are being added to CI so that neither class of problem has
to be caught by review again.

## Files

| file | contents |
| --- | --- |
| `evidence/frontend-angular-22/audit-before-all.json` | full `npm audit --json` at `c2472d77b` |
| `evidence/frontend-angular-22/audit-before-prod.json` | same with `--omit=dev` |
| `evidence/frontend-angular-22/audit-after-all.json` | full `npm audit --json` on the branch |
| `evidence/frontend-angular-22/audit-after-prod.json` | same with `--omit=dev` |
| `evidence/frontend-angular-22/advisories-before.tsv` | all 114 advisories with severity, CVSS and whether each is still present after |
| `evidence/frontend-angular-22/direct-dependencies.tsv` | every direct dependency, declared and resolved, before and after |
