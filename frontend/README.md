# Frontend

Angular 19 application. Generated with [Angular CLI](https://github.com/angular/angular-cli) v19.

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
npm run build                  # production build → dist/
npm run watch                  # dev build with rebuild on changes
npm run build-mym              # production build with base-href /epicstaff/
```

---

## Code quality checks

### All files (`src/**`)

**ESLint (TypeScript):**
```powershell
npm run lint              # check without changes
npm run lint:fix          # check with autofix
```

**Prettier (`.ts`, `.html`, `.scss`, `.json`):**
```powershell
npx prettier --check "src/**/*.{ts,html,scss,json}"         # check only, no writes
npm run format                                              # format files in place
```

**TypeScript type-check:**
```powershell
npx tsc --noEmit -p tsconfig.app.json     # type-check without emitting files
npm run build                              # full build = type-check + compile
```

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

```powershell
npm run lint; if ($?) { npx prettier --check "src/**/*.{ts,html,scss,json}" }; if ($?) { npx tsc --noEmit -p tsconfig.app.json }
```

Stops at the first failing check.

---

## Git hooks (Husky)

Hooks are installed automatically on `npm install` via the `prepare` script ([package.json](./package.json#L11)). Hook scripts live in [.husky/](./.husky/); the `.git` directory is in the **parent** monorepo folder (`../`).

### Active hooks

Only `pre-commit` is configured ([.husky/pre-commit](./.husky/pre-commit)). No other hooks (`pre-push`, `commit-msg`, etc.) are set up.

### `pre-commit` logic

1. **Skip merge commits.** If a merge is in progress (`MERGE_HEAD` exists), the hook exits with code 0 without running any checks. This prevents Prettier from reformatting files coming from the upstream branch.
2. **Run `lint-staged`.** If `frontend/node_modules/.bin/lint-staged` exists — it runs. If `node_modules` is missing — the hook **silently skips** the check (convenient for teammates without a built frontend, but be aware: commits will go through unlinted if `node_modules` is broken).

### What the hook does NOT do

- Does not check files outside `src/**` (`*.json`, `*.md`, config files)
- Does not run `tsc` — type errors slip through if the file is lint-clean
- Does not run tests
- Does not validate commit messages
- Does not fire on `git push` or during merge commits

### Bypassing the hook

```powershell
git commit --no-verify -m "..."     # skip the hook — use only when necessary
```
