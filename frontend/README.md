# Frontend

Angular 22 application. Generated with [Angular CLI](https://github.com/angular/angular-cli) v19, upgraded to v22 (EST-3802).

Node version is pinned in [.nvmrc](./.nvmrc) and enforced by the `engines` field; the Docker
image uses the same version. Install with `npm ci` rather than `npm install` — the lockfile
is authoritative, and `npm install --force` used to be needed only to paper over a peer
conflict that no longer exists.

## Development server

```powershell
npm start                       # ng serve --no-hmr → http://localhost:4200
npm start -- --port 4300        # run on a custom port → http://localhost:4300
```

The server automatically reloads the app when source files change.

## Pointing the frontend at a different backend

Backend URLs live in [src/environments/environment.ts](./src/environments/environment.ts), which is tracked by git — editing it directly leaves the file permanently dirty in `git status`. Use a personal override instead:

```powershell
cp src/environments/environment.local.example.ts src/environments/environment.local.ts
# edit environment.local.ts — set apiUrl / realtimeApiUrl
npm run start:local
```

`environment.local.ts` is listed in [.gitignore](../.gitignore), so it never shows up as a pending change. The example file documents the usual targets: a remote stand (no local backend needed), a local backend behind docker/nginx, or services exposed directly on their ports.

A plain `npm start` keeps using the repository's `environment.ts`. The swap is wired through the `local` configuration in [angular.json](./angular.json) via `fileReplacements` — the same mechanism `test` and `production` builds use.

## Build

```powershell
npm run build                  # production build → dist/epicstaff-frontend/
npm run watch                  # dev build with rebuild on changes
npm run build-mym              # production build with base-href /epicstaff/
```

`allowedCommonJsDependencies` in [angular.json](./angular.json) lists `papaparse` and `jszip`.
Both are CommonJS-only with no ESM build published — papaparse has none even in its latest
release, and jszip arrives through `docx-preview`, so its import is not ours to change. The entry
suppresses the build warning; it does not change the output. Both land in the lazy chunk for the
file-preview screen, not the initial bundle, so the tree-shaking cost is confined to that route.
Add to this list only after confirming a package genuinely has no ESM entry point.

## Tests

```powershell
npm test                       # run once and exit
npm test -- --watch            # re-run on change
npm test -- --coverage         # with coverage report
npm test -- --filter clearStale  # run a subset by test name
```

Runs through the [`@angular/build:unit-test`](./angular.json) builder on **Vitest**, in Node
with jsdom — no browser needed. Karma was removed in EST-3802: it is deprecated upstream, its
config here had been fully commented out, and the builder only exists from Angular 22.

Spec files are `src/**/*.spec.ts`. That glob is set explicitly in [angular.json](./angular.json)
because the builder's default also matches `**/*.test.ts`, which would wrongly pick up
[src/environments/environment.test.ts](./src/environments/environment.test.ts) — an environment
config, not a test.

---

## Code quality checks

### All files (`src/**`)

**ESLint (TypeScript):**
```powershell
npm run lint              # check without changes — fails on any warning
npm run lint:fix          # check with autofix
```

`lint` carries `--max-warnings=0`, the same strictness as the pre-commit hook and CI. Note that
ESLint checks import **order** but not spacing — formatting is Prettier's job, below.

**Prettier (`.ts`, `.html`, `.scss`, `.json`):**
```powershell
npm run format:check      # check only, no writes
npm run format            # format files in place
```

Both use the same glob, so there is one definition of "which files are formatted".

**TypeScript type-check:**
```powershell
npx tsc --noEmit -p tsconfig.app.json     # type-check without emitting files
npm run build                              # full build = type-check + compile
```

**Undeclared imports:**
```powershell
node ../scripts/check-undeclared-imports.mjs      # run from frontend/ or the repo root
```

Fails when `src/` imports a package that `package.json` does not declare. Such an import may
still resolve through a transitive dependency or a stale lockfile entry, and then break on a
clean install — which is exactly what happened with `uuid`, `jsonc-parser` and
`@types/json-schema` before EST-3802.

**Dependency advisories:**
```powershell
npm audit --audit-level=high    # what CI enforces
npm audit                       # everything, including moderate and low
```

**Third-party licence notices:**
```powershell
node ../scripts/check-third-party-notices.mjs        # are the notices in sync?
node scripts/generate-third-party-notices.mjs       # regenerate after a dependency change
```

[THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) documents the licences of every
**production** dependency, so it has to be regenerated whenever that set changes. The check
compares the lockfile hash stamped in the file header, so it needs neither network access nor a
`license-checker` run. The generator does need network — it fetches `license-checker` through
`npx`.

### Staged files only

The `lint-staged` config lives in [package.json](./package.json) under the `"lint-staged"` field. Manual run:

```powershell
npx lint-staged              # same as the commit hook: ESLint --fix + Prettier on staged files
npx lint-staged --debug      # verbose log — useful for debugging
npx lint-staged --no-stash   # skip auto-stash of unsaved changes
```

What `lint-staged` runs:

| Pattern         | Commands                                             |
| --------------- | ---------------------------------------------------- |
| `src/**/*.ts`   | `eslint --fix --max-warnings=0` → `prettier --write` |
| `src/**/*.html` | `prettier --write`                                   |
| `src/**/*.scss` | `prettier --write`                                   |

After autofix, `lint-staged` re-stages the modified files with `git add`, so they end up in the same commit. If ESLint fails (any warning or unfixable error), the commit is aborted and changes are restored from stash.

### Full pre-PR check

The same sequence CI runs, in the same order, plus a type-check that CI only covers later via
the Docker build:

```powershell
npm run lint; if ($?) { npm run format:check }; if ($?) { node ../scripts/check-undeclared-imports.mjs }; if ($?) { node ../scripts/check-third-party-notices.mjs }; if ($?) { npm test }; if ($?) { npm audit --audit-level=high }; if ($?) { npx tsc --noEmit -p tsconfig.app.json }
```

Stops at the first failing check. If this passes, `frontend-checks` in CI will too.

### What CI runs

The `frontend-checks` job in [../.github/workflows/pr.yml](../.github/workflows/pr.yml) runs on
every PR to `main` — including backend-only ones, deliberately: the advisory database moves on
its own, so a PR that touches nothing here can still be the first to surface a new finding.

| Step                 | Command                                                 |
| -------------------- | ------------------------------------------------------- |
| install              | `npm ci` — with `HUSKY=0`, CI has no use for git hooks   |
| lint                 | `npm run lint`                                           |
| format               | `npm run format:check`                                   |
| undeclared imports   | `node scripts/check-undeclared-imports.mjs`              |
| licence notices      | `node scripts/check-third-party-notices.mjs`             |
| tests                | `npm test`                                               |
| advisories           | `npm audit --audit-level=high`                           |

The Docker `build` job depends on `frontend-checks`, so a red check blocks the build rather than
running beside it. The production build itself — and with it the full `tsconfig.app.json`
type-check — happens in that Docker job.

---

## Git hooks (Husky)

Hooks are installed automatically on `npm install` via the `prepare` script ([package.json](./package.json#L12)). Hook scripts live in [.husky/](./.husky/); the `.git` directory is in the **parent** monorepo folder (`../`).

Set `HUSKY=0` to skip the install — the `prepare` script needs the repo root and a `.git`
directory, so it fails anywhere that has neither. Both the Docker image and CI set it. Use that
rather than `npm ci --ignore-scripts`, which would also skip esbuild's `postinstall` and the
native prebuild steps for `lmdb`, `msgpackr-extract` and `@parcel/watcher`.

### Active hooks

Only `pre-commit` is configured ([.husky/pre-commit](./.husky/pre-commit)). No other hooks (`pre-push`, `commit-msg`, etc.) are set up.

### `pre-commit` logic

1. **Skip merge commits.** If a merge is in progress (`MERGE_HEAD` exists), the hook exits with code 0 without running any checks. This prevents Prettier from reformatting files coming from the upstream branch.
2. **Run `lint-staged`.** If `frontend/node_modules/.bin/lint-staged` exists — it runs. If `node_modules` is missing — the hook **silently skips** the check (convenient for teammates without a built frontend, but be aware: commits will go through unlinted if `node_modules` is broken).

### What the hook does NOT do

- Does not check files outside `src/**` (`*.json`, `*.md`, config files)
- Does not run `tsc` — type errors slip through if the file is lint-clean
- Does not run tests
- Does not check for undeclared imports, advisories or stale licence notices
- Does not validate commit messages
- Does not fire on `git push` or during merge commits

Everything in that list is covered by CI instead, so a clean commit is not the same as a green
PR. Run the [full pre-PR check](#full-pre-pr-check) before opening one.

### Bypassing the hook

```powershell
git commit --no-verify -m "..."     # skip the hook — use only when necessary
```
