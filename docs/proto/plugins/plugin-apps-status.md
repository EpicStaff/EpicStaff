---
id: plugin-apps-status
title: Plugin apps — build status and morning test guide
type: status
status: draft
tags: [plugins, prototype, plugin-apps]
created: 2026-10-07
updated: 2026-10-07
related: [alignment-plugin-apps, plugin-apps-plan]
---

# Plugin apps — build status and morning test guide

Built overnight on 2026-10-07 against [[alignment-plugin-apps]] and the frozen contracts in [[plugin-apps-plan]].
**Nothing is committed** — every change is in the working tree of `proto/plugins-06-10-26`.

## What was built

| Area | Where | What |
|---|---|---|
| KV tables travel in exports | `src/django_app/tables/import_export/` | New `KeyValueTable` entity (definition only, no rows); a flow export carries the tables its KV nodes use; on import a KV node binds to the imported table first, then falls back to the old by-name rule. `IMPORT_VERSION` unchanged (3). |
| Plugins ship KV tables | `src/django_app/plugins/` | `key_value_table` resource type; installed as `<plugin_id>__<name>` (e.g. `chat_admin__conversations`); always created new; a bundled KV node may only use a table the bundle ships (blocks reading the org's own tables); suspend blocks org flows that use the table; delete removes the table and its rows. |
| Real framework apps | `plugins/asset_views.py`, `manifest.py`, `bundle_reader.py`, `ui_token.py` | CSP now allows ES modules, lazy chunks, web fonts and injected styles (still no inline scripts / eval / network); `Access-Control-Allow-Origin: *` on plugin files; fonts/images/.txt/.map/.mjs allowed; UI ≤ 300 files / 20 MB, zip ≤ 30 MB; page link valid 12 h; plugin documents are **refused as top-level pages** (only served into the sandboxed frame). |
| Bridge v2 | `frontend/src/app/features/plugins/bridge/v2/` | `kv.list`, `kv.get` (pinned to the granted table, ids never reach the page), `nav.changed` / `nav.navigate` (deep links), `theme.changed` (EpicStaff tokens as `--es-*` + dark/light). v1 is untouched; the old chat-bot sample keeps bridge 1. |
| Deep links | `app.routes.ts`, host page, route matcher | `/plugins/<id>/<app path>` survives refresh; back/forward move one app screen at a time. |
| Dev mode | `PLUGINS_DEV_MODE` setting, `POST/DELETE /api/plugins/{id}/dev-ui/`, Settings → Plugins → **Dev mode** | An installed plugin's app loads live from `http://localhost:<port>/` for the admin who set it, with a DEV banner, live reload and the real bridge. Off unless the instance runs with `PLUGINS_DEV_MODE=True`. |
| SDK + CLI | `plugin-sdk/` | `connect()` client (handshake, `flows.runAndWait`, `kv.*`, nav sync, theme), in-memory storage stand-in, mock host for standalone runs, CLI `validate` / `pack`. README = author guide. |
| Chat Admin sample | `plugin-samples/chat-admin/` | `plugin/` (plugin.json + generated resources.json) and `app/` (Angular 22.2.1, hash routing, lazy screens Chat / Conversations / Conversation / About, bundled Inter font). Packed zip: `../chat-admin-plugin.zip`. |

Flow inside the sample: Start `{conversation_id, question}` → KV read (transcript) → Python "Format history" → Task
"Answer" → Python "Append turn" (builds the conversation record) → KV write → End `{answer, conversation_id}`. The app
sends only the id and the question; the flow keeps the transcript.

## Verified

- **Backend:** `make django-tests` (plugins, import/export, KV service/API, graph versioning) — `1134 passed, 6 skipped`.
- **Frontend:** lint, format:check, undeclared imports, third-party notices, build, full unit suite `1393 passed`.
- **SDK:** `82 passed`; sample app builds; `validate` 0 errors; zip readable by Python `zipfile`.
- **Reviews:** backend, frontend (host), frontend (SDK + app) and security reviews — every finding fixed, including the
  security one (plugin documents opened as top-level pages could act as a 12 h phishing page on EpicStaff's domain).
- **On the local stack, in a separate test org** (your org was not touched):
  install review lists table + access + Python warning → install → nav icon → app inside EpicStaff's shell, no CSP
  errors, modules/chunks/fonts load with `ACAO *` · KV read + "Format history" ran in the real sandbox; the Task failed
  only on the placeholder OpenAI key · Conversations list (25 seeded rows), paging, search, sort, detail · deep-link
  refresh restores the screen · back/forward one step each · live theme switch · in-frame `fetch` and `parent.document`
  blocked, origin `null` · dev mode from `ng serve` on 4300 with live reload and real data · DEV badge, "Turn off dev
  mode" · top-level `index.html` / `icon.svg` → 404 · suspend (icon gone, page says suspended) / resume · delete
  preview lists the table; delete leaves no plugin, registry, assets, flow, table or rows · the final zip reinstalls.

## Not verified (needs you)

1. **A real chat answer.** No OpenAI key was available, so the "Append turn" node and the KV write have run only in
   tests (the Python code is tested the way the sandbox wraps it). This is the first thing to try.
2. The old v1 `chat-bot` plugin in your own org (covered by the frozen v1 contract spec and backend tests, not clicked).

## Morning test (≈10 minutes)

1. **Env** — the stack is running with two values passed on the command line, not in `src/.env` (the agent can't edit
   it). Add them to `src/.env` before your next `docker compose up`, otherwise compose refuses to start (`:?`):
   ```
   PLUGINS_DEV_MODE=True          # local dev stack only; False everywhere else
   DJANGO_API_KEY=<random value>  # was "none": every Key-Value node failed on this stack ("DJANGO_API_KEY is not configured")
   ```
   Any random string works (`openssl rand -hex 32`); django_app seeds it as the system key at startup. The value used
   tonight is in the session scratchpad; a new value is fine — recreate `django_app crew realtime` after changing it.
2. Settings → Plugins → **Add plugin** → drop `../chat-admin-plugin.zip` → enter your OpenAI key → tick the code
   warning → Add plugin.
3. Click the new **Chat Admin** icon in the left bar → **Chat** → ask two questions → answers appear.
4. **Conversations** → your conversation is listed → open it → refresh the browser on that URL → same screen.
5. Optional dev mode: `cd plugin-samples/chat-admin/app && node node_modules/@angular/cli/bin/bootstrap.js serve`
   (port 4300; local Node 24.3 is below Angular CLI's 24.15 minimum, hence `bootstrap.js`) → Settings → Plugins →
   Chat Admin → **Dev mode** → `http://localhost:4300/` → open the plugin → DEV banner; edit a template → live reload.

## Decisions taken without you (change any)

- The route uses the plugin's database id (`/plugins/7/conversations/…`), not its slug (`/plugins/chat-admin/…`).
- The dev URL belongs to the admin who set it; other users keep the installed app.
- A deep link to a **v1** plugin ignores the path (the fragment is part of the v2 handshake).
- While the user is navigating the host, the page's `nav.changed` is ignored (a page can't trap the user).
- `turns` in the record counts every question asked, including pairs dropped to stay under 200 KB.
- Plain (non-plugin) flow imports now carry and create their KV tables, so importing such a flow needs
  `key_value_tables:create`.
- The frozen v1 contract spec had two *registry* assertions loosened (v1 is no longer the only version); no v1
  behaviour assertion changed.

## Known gaps / follow-ups

- Light mode can't be switched from EpicStaff's UI today (nothing applies `.my-app-light`); detection works.
- While a plugin is suspended its table is still readable through EpicStaff's own Key-Value Tables page.
- The delete preview labels the table count with the generic "Key value tables" and shows no row count.
- In a fresh org the install creates its own `gpt-4o-mini` LLM model row, so delete removes it too (v1 behaviour).
- The SDK's mock host ships as a small lazy chunk in production builds (never downloaded inside EpicStaff).
- In dev mode any page loaded in the frame gets the bridge with the dev user's permissions (banner says so).
- Secrets in the plugin app: still **open** — nothing built.

## Local stack state left behind

- Images `django_app` / `frontend` `:plugins-proto` rebuilt; migration `plugins.0002_dev_ui_and_key_value_tables`
  applied. DB backup taken first: `../epicstaff-db-backup-2026-10-07-pre-plugin-apps.sql.gz`.
- Test org **"Plugin E2E (Claude test)"** with user `plugin-e2e@example.test` (Org Admin, throwaway password in the
  session scratchpad) and Chat Admin installed there. Remove with Django admin or:
  `docker exec -i django_app python manage.py shell -c "from rbac.models import Organization; from tables.models import User; User.objects.filter(email='plugin-e2e@example.test').delete(); Organization.objects.filter(name='Plugin E2E (Claude test)').delete()"`
  (delete the plugin from Settings first so its resources go through the normal path).
- The Playwright browser profile is logged in as the test user.

## Proposed commits (not run — waiting for your yes)

```
git -C <SRC> add src/ && git -C <SRC> commit -m "chore(proto): plugins — backend: key-value tables in plugins, framework app serving, dev mode"
git -C <SRC> add frontend/ && git -C <SRC> commit -m "chore(proto): plugins — frontend: bridge v2, deep links, theme, dev mode"
git -C <SRC> add plugin-sdk/ plugin-samples/ && git -C <SRC> commit -m "chore(proto): plugins — plugin SDK, CLI and Chat Admin sample app"
git -C <SRC> add docs/proto/plugins/ && git -C <SRC> commit -m "chore(proto): plugins — docs: idea, rules, architecture, protocols, plugin apps"
git -C <SRC> push
```
