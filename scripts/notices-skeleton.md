<!-- Sections between BEGIN/END GENERATED markers are produced by scripts — do not edit by hand. -->

# Third-Party Notices

This file lists third-party open-source software bundled into EpicStaff. It covers **production** npm dependencies of the Angular frontend (declared in `frontend/package.json`, resolved via `frontend/package-lock.json`), assets embedded in the prebuilt epicchat-widget bundle, and **main** Python dependencies of the backend microservices under `src/`.

Development-only dependencies (test runners, linters, build tooling) are out of scope — they are not shipped to users.

The EpicStaff project itself is licensed under the terms found in [LICENSE](./LICENSE). Nothing in this notices file modifies or supersedes that license.

---

<!-- BEGIN GENERATED: frontend -->

<!-- END GENERATED: frontend -->

<!-- BEGIN GENERATED: backend -->

<!-- END GENERATED: backend -->

---

## How to refresh this file

Each half of this file is regenerated independently. A frontend dependency change does not need the Python toolchain, and a backend change does not need Node.

### Frontend (npm + embedded assets)

Whenever frontend production dependencies change (additions, version bumps, removals in `frontend/package.json`), or the prebuilt widget bundle at `frontend/public/epicchat-widget/` is replaced:

```powershell
cd frontend
npm install
node scripts/generate-third-party-notices.mjs
```

The generator invokes `npx --yes license-checker --production --json` internally — no extra devDependency is needed. It rewrites ONLY the `frontend` region of this file. Embedded-asset entries are maintained by hand in `frontend/scripts/embedded-assets-notices.md` and inlined by the generator.

### What the frontend refresh covers

- Walks every package reachable from `frontend/package.json` `dependencies` (not `devDependencies`) via `npm` resolution.
- Reads each package's SPDX license identifier from its installed `package.json` and the verbatim text from its shipped LICENSE / COPYING / NOTICE file when present.
- Sorts entries alphabetically and groups them by SPDX identifier in the summary table.

### Backend (Python)

Whenever any backend service's `pyproject.toml` dependencies change (`src/django_app`, `src/crew`, `src/agent`, `src/manager`, `src/knowledge`, `src/realtime`, `src/sandbox`, `src/webhook`, `src/auditor`):

```powershell
python scripts/generate-python-notices.py
```

Stdlib only; `pip-licenses` is installed into a throwaway venv at `scripts/.tmp_notices_venv/` and removed afterwards. `uv` must be on `PATH`. It rewrites ONLY the `backend` region of this file.

## Manual overrides applied

- The EpicStaff frontend project itself (`epicstaff-frontend`) is filtered out of the npm list — this notices file only covers third-party code.
- Vendored code (copied into the repository rather than installed) is maintained by hand inside each generator: `## Vendored code` for the frontend, `### Vendored Libraries` for the backend.
