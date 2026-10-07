---
id: plugin-apps-plan
title: Plugin apps — implementation plan (frozen contracts + workstreams)
type: plan
status: in-progress
tags: [plugins, prototype, plugin-apps]
created: 2026-10-07
updated: 2026-10-07
related: [alignment-plugin-apps, plugin-bridge-v1, plugin-package-format, plugins-rules, plugins-api-contract]
---

# Plugin apps — implementation plan

Requirements: [[alignment-plugin-apps]] (`alignment-plugin-apps-2026-10-07.md`, authoritative). Produced by the
`architect` agent against `proto/plugins-06-10-26` @ `c20092c53`. Every `file:line` is relative to the repo root
(`src/django_app/...` paths are written from `src/django_app/` where noted). **§1 is a frozen contract — writers
implement it exactly; deviations are reported back, not improvised.**

## 0. Corrections to the coordinator's notes (already folded into §1–§2)

| # | Note | Reality | Plan |
|---|---|---|---|
| 1 | `kv.get` via lookup | lookup returns a 200-char preview only (`tables/services/key_value_table_service.py:149-165`, view `tables/views/model_view_sets.py:2543-2549`); full value only from `GET /api/key-value-table-entries/{id}/` (`model_view_sets.py:2599-2602`), not table-scoped | `kv.get {table,key}` = list with a new exact `key` filter → retrieve → host verifies `table` & `key`. DB ids never reach the page |
| 2 | base href `./` | `<base>` blocked by CSP `base-uri 'none'` (`plugins/asset_views.py:20`); relative URLs already resolve against `/api/plugin-ui/<token>/`; HashLocationStrategy needs no base | Sample `index.html` has **no `<base>`**; CLI `validate` warns on one |
| 3 | hash routing optional | **Required**: opaque-origin pages may only change query/fragment via pushState; also pushState inside the frame adds entries to the **top** history (double Back) | SDK patches `history.pushState` → `replaceState` + `nav.changed`; the host owns history |
| 4 | dev: re-handshake on frame `load` | New page posts `ready` **before** iframe `load`; current code ignores a 2nd `ready` once a port exists (`plugin-bridge-host.service.ts:188`) | Dev reset trigger = a new `ready` (close old port, new port); ignore `load` after the first. Production unchanged |
| 5 | SPA CSP may block dev iframe | Gateway CSP is **Report-Only** with no `frame-src` (`src/nginx/templates/default.conf.template:49`) | No nginx change |
| 6 | CORS | django-cors-headers acts only on `DJANGO_CORS_ALLOWED_ORIGINS` (`django_app/settings/cors.py:5-7`), ignores `Origin: null`, does not strip our header; nginx `/api` has no `add_header` (`default.conf.template:112-120`) | Asset view sets `Access-Control-Allow-Origin: *` itself |
| 7 | token | Signed `{plugin,org,user}` (`plugins/services/ui_token.py:25-28`), 600 s (`:15`); each asset request re-checks signature+age, plugin in org, not suspended, has UI, user active+member, `plugins:use`, READY, canonical allowed path (`ui_service.py:68-120`) | `MAX_AGE_SECONDS = 43200` |
| 8 | alias→id | v1 resolves from **ui-session** `access[].resource_id` (`ui_service.py:62-65`, `buildAccessPolicy` at `plugin-bridge-host.service.ts:114`); presenter hard-codes FLOW (`presenter.py:71`); frontend policy drops non-`flow` (`access-policy.ts:35`) | Presenter resolves per access type; policy gets a per-bridge-version type table |
| 9 | name prefix | Secret: `CHAT_BOT__SLOT` (`manifest.py:193-195`). KV table names unique per org iexact, max 255, no char pattern (`tables/models/key_value_models.py`, `tables/constants/key_value_constants.py:3`) | `chat_admin__<name>` built by `PluginPackage`; >255 after prefix → reject; conflict check iexact |
| 10 | **data-leak path** | A KV node is re-bound **by name** to any org table (`key_value_table_service.py:255-293`) — a plugin flow could read the org's `customers` table and return rows to the app via `flows.run` | Manifest **rejects** any KV node whose table is not shipped in `resources.json` |
| 11 | silent unbinding | A KV node binds only if the installer holds the mode's perms (`MODE_PERMISSIONS`, `key_value_table_service.py:39-43`), else imports unbound silently | Install also requires those `key_value_tables` perms |
| 12 | bridge 64 KB cap | `bridge-protocol.ts:33`; sending the transcript each turn would hit it | The flow **reads the transcript from KV**; the app sends only `{conversation_id, question}` |
| 13 | dark/light | `.my-app-light` exists (`frontend/src/styles/_variables.scss:695-758`) but nothing applies it — EpicStaff is always dark | MutationObserver on the class; light mode testable via devtools only |
| 14 | bundle limits | zip entry cap 200 (`plugins/services/bundle_reader.py:17`) < 300 UI files | zip 30 MB / 400 entries / 60 MB unpacked; client check (`plugin-install-dialog.component.ts:39,281`) → 30 MB |
| 15 | Angular licence file | Angular ≥17 writes `3rdpartylicenses.txt` **outside** `browser/`; `favicon.ico` from `public/` | Allow `.txt`, `.ico` anyway (harmless) |

Family note: no new **node type** → the `<type>_node_list` contract does not apply; `NODE_RELATIONS` /
`NODE_COPY_HANDLERS` unchanged; `DEPENDENCY_ORDER` gains one **entity**.

## 1. Frozen contracts

### 1.1 Manifest (`plugin.json`)
- `format_version` stays **1** (additive). `SUPPORTED_BRIDGE_VERSIONS = {1, 2}` (`manifest.py:33`).
- `access[]`: `{alias, type: "flow"|"key_value_table", ref, actions}`. Actions by type: `flow` → `run`,
  `sessions.read`, `sessions.stop`; `key_value_table` → `read`. `ref` = a `Flow` / `KeyValueTable` entity id in `resources.json`.
- New rejections (each a `400 invalid_plugin` item): `key_value_table` access needs `bridge >= 2`; action invalid for
  type; every `KeyValueNode` with `key_value_table` or `key_value_table_name` set must have `key_value_table` == a
  `KeyValueTable` id in `resources.json`; prefixed table name ≤ 255.
- Installed table name: `plugin_id.replace('-', '_') + '__' + name` (e.g. `chat_admin__conversations`). No new top-level keys.

### 1.2 Export entity (import format v3; `IMPORT_VERSION` stays 3)
```json
"KeyValueTable": [{"id": 1, "name": "conversations", "description": "One entry per chat conversation."}]
```
Definition only — rows never exported. `DEPENDENCY_ORDER`: `EntityType.KEY_VALUE_TABLE = "KeyValueTable"` after
`WEBHOOK_TRIGGER`, before `GRAPH` (`import_export/constants.py:35-36`). `ENTITY_RESOURCE_MAP[KEY_VALUE_TABLE] =
KEY_VALUE_TABLES`. A flow export includes the tables its KV nodes reference; KV node export unchanged
(`key_value_table` id + `key_value_table_name`). **Import binding order** for a KV node: (1) its `key_value_table` id
is mapped in IDMapper → bind that table (same org), still gated by `can_configure(user, table, mode)`; (2) else today's
`resolve_reference` by id/name. `find_existing` reuses the importing org's table by `name__iexact`; `None` when
`org_id` is None. Older servers ignore the key (import walks `DEPENDENCY_ORDER`, `import_service.py:79-84`).

### 1.3 REST API changes
- **Plugin object (list + detail):** `access[].type` may be `key_value_table` (`resource_name` = table name);
  `contents.key_value_table`; `resources[].type: "key_value_table"`; **new** `dev_mode_available: bool` (instance
  flag), `dev_ui_url: string|null`, `dev_ui_user: int|null`.
- **Resource type key** `key_value_table` → RBAC `key_value_tables` (install needs create; delete needs delete).
- **Inspect:** `contents[]` item `{"type":"key_value_table","ref":"1","name":"chat_admin__conversations"}`;
  `access[]` `{"alias":"conversations","type":"key_value_table","ref":1,"resource_name":"chat_admin__conversations","actions":["read"]}`;
  `conflicts[].type` may be `"key_value_table"` (`"A key-value table named 'X' already exists."`, 409 at install);
  `missing_permissions` may list `key_value_tables` with `create` (table) and per bundled KV node mode
  (read→`read`, write→`update`, delete→`read`+`delete`).
- **Delete preview:** `resources` / `resource_counts` include `key_value_table`; `affected_resources.key_value_tables`
  (already mapped, `tables/services/organization_deletion.py:54`); `external_usages` reports org flows whose KV nodes
  use the table (`{"type":"key_value_table",…,"used_by":[{"type":"flow"}]}`).
- **`POST /api/plugins/{id}/ui-session/`:** production — `expires_in: 43200`, `dev_mode: false`, access entries incl.
  KV. Dev — when the flag is on and `dev_ui_url` set and requester is `dev_ui_user`:
  `{"url":"http://localhost:4300/","token":"","expires_in":null,"dev_mode":true, …rest unchanged}`; everyone else gets
  production. Other checks unchanged (suspended/not ready/no UI → 409).
- **New `POST /api/plugins/{id}/dev-ui/`** (`plugins:update`, JWT only, org-scoped): body `{"url":"http://localhost:4300/"}`
  → sets `dev_ui_url` + `dev_ui_user = request.user` → 200 `PluginDetail`. 400 `invalid` unless the URL matches
  `^http://(localhost|127\.0\.0\.1)(:\d{1,5})?(/[A-Za-z0-9._~/%-]*)?$` (no userinfo, query, fragment; ≤255).
  409 `plugin_dev_mode_disabled` when the flag is off. 403/404 as usual.
- **`DELETE /api/plugins/{id}/dev-ui/`** (`plugins:update`) → clears both → 200 `PluginDetail`; allowed when the flag is off.
- **`GET /api/key-value-table-entries/?table=<id>&key=<exact>`:** new exact filter (additive, existing org-scoped viewset).

### 1.4 Asset serving (`GET /api/plugin-ui/{token}/{path}`)
- **CSP (exact):** `sandbox allow-scripts; default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; media-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'`
- **Add** `Access-Control-Allow-Origin: *`; keep every existing header (`asset_views.py:23-32`). No credentials.
- **Types:** `.html` `text/html; charset=utf-8` · `.js`/`.mjs` `text/javascript; charset=utf-8` · `.css`
  `text/css; charset=utf-8` · `.json`/`.map` `application/json` · `.txt` `text/plain; charset=utf-8` · `.svg`
  `image/svg+xml` · `.png` `image/png` · `.jpg`/`.jpeg` `image/jpeg` · `.gif` `image/gif` · `.webp` `image/webp` ·
  `.ico` `image/x-icon` · `.woff` `font/woff` · `.woff2` `font/woff2` · `.ttf` `font/ttf` · `.otf` `font/otf`.
- **Limits:** UI ≤ 300 files, ≤ 20 MB; zip ≤ 30 MB, ≤ 400 entries, ≤ 60 MB unpacked; icon unchanged (64 KB).

### 1.5 Bridge v2 (v1 table frozen; v2 is a separate table)
- **Handshake** as v1 with `v: 2`. `init.context = {plugin:{id,version,name}, access:[{alias,type,actions}],
  nav:{path}, theme:{mode:"dark"|"light", tokens:{"--es-…":"<css value>"}}}`. The host also puts `nav.path` into the
  iframe URL fragment (`…/index.html#<path>`).
- **Event envelope:** `{v:2, kind:"event", topic, subscription: string|null, data}`; host-pushed topics use `subscription: null`.

| Method | Params | Needs | HTTP | Result |
|---|---|---|---|---|
| `bridge.hello`, `flows.run`, `sessions.get`, `sessions.subscribe`, `sessions.unsubscribe`, `sessions.stop` | = v1 | = v1 | = v1 | = v1 (`methods` lists the v2 table) |
| `kv.list` | `{table: alias, search?: str ≤512, ordering?: "key"\|"-key"\|"updated_at"\|"-updated_at" (default "key"), limit?: 1..100 (default 20), offset?: ≥0 (default 0)}` | `read` on a `key_value_table` alias | `GET /api/key-value-table-entries/?table=<id>&ordering=&limit=&offset=[&search=]` | `{count, items:[{key, value_preview, value_truncated, created_at, updated_at}]}` — items whose `table` ≠ id dropped; `id`, `table`, `updated_by_*` stripped |
| `kv.get` | `{table: alias, key}` — key `^[A-Za-z_][A-Za-z0-9_]*$`, ≤512, else `bad_request` (no HTTP) | `read` | 1) `GET …/key-value-table-entries/?table=<id>&key=<key>&limit=1` (empty → `not_found`); 2) `GET …/key-value-table-entries/<entry id>/`; require `table == id && key == key` else `not_found` | `{key, value, created_at, updated_at}` |
| `nav.changed` | `{path, replace?: bool}` | — | none (host router) | `{}` |

- **Events:** `nav.navigate {path}` (host URL changed by back/forward, sidenav click, address bar);
  `theme.changed {mode, tokens}`; `session.*` / `subscription.closed` as v1.
- **Path grammar:** ≤1024 chars, `^/([A-Za-z0-9\-._~%]+(/[A-Za-z0-9\-._~%]+)*)?(\?[A-Za-z0-9\-._~%=&+]*)?$`, no
  `.`/`..` segments, valid `%` escapes; else `bad_request`.
- **Limits:** v1 limits + `nav.changed` ≤ 120 / 60 s → `rate_limited`. Error codes unchanged.
- **Theme tokens** (from `getComputedStyle(document.body)`; stable public set — add, never rename):
  `--es-color-background`←`--color-background-body`, `--es-color-surface`←`--color-surface-card`,
  `--es-color-surface-raised`←`--color-modals-background`, `--es-color-sidenav`←`--color-sidenav-background`,
  `--es-color-text`←`--color-text-primary`, `--es-color-text-secondary|-tertiary|-disabled`←`--color-text-*`,
  `--es-color-accent|-hover|-active`←`--accent-color*`, `--es-color-input-background|-border|-placeholder`←`--color-input-*`,
  `--es-color-border`←`--color-border`, `--es-color-divider`←`--color-divider-regular`,
  `--es-color-divider-subtle`←`--color-divider-subtle`, `--es-color-success`←`--success-color`,
  `--es-color-warning`←`--color-warning`, `--es-color-error`←`--color-status-error`, `--es-focus-ring`←`--focus-ring`,
  `--es-font-family`←`--font-family`. Mode = `light` iff `body` or `html` has class `my-app-light`, else `dark`.

### 1.6 Chat Admin conversation record (flow writes; app reads)
```json
{"title": "first question, ≤80 chars", "turns": 2,
 "messages": [{"role": "user|assistant", "content": "…", "at": "ISO-8601"}],
 "started_at": "ISO", "updated_at": "ISO", "conversation_id": "c_<24 hex>"}
```
KV key = conversation id (app generates `c_` + 24 hex). Record ≤ 200 000 bytes (KV max 256 KiB,
`key_value_constants.py:5`); drop oldest message pairs first.

## 2. Workstreams

### (A) `backend-dev` — django_app
| # | File(s) | Change |
|---|---|---|
| A1 | `tables/import_export/enums.py`, `constants.py:9-53`, `permissions.py:15-42`, new `serializers/key_value_table.py` (`id, name, description`), new `strategies/key_value_table.py`, `tables/apps.py:107-148` (register) | New KV export entity per §1.2: strict org scope; `find_existing` iexact; `create_entity` stamps org. Follow new-import-export skill Procedure A. **No `IMPORT_VERSION` bump.** |
| A2 | `strategies/graph.py:57-119` | `deps[KEY_VALUE_TABLE]` = the flow's KV node table ids (non-null, same org). **Not** in the node strategy (partial copy/paste unchanged) |
| A3 | `strategies/nodes/key_value_node.py:25-40` + `tables/services/key_value_table_service.py:255-293` | Binding order §1.2; the rule lives in `KeyValueTableService` (e.g. `imported_table_id` arg) |
| A4 | `tables/views/model_view_sets.py:2577-2582` | `key = CharFilter(field_name="key", lookup_expr="exact")` |
| A5 | `plugins/resource_types.py` | `PluginResourceType.KEY_VALUE_TABLE = "key_value_table"`; `RESOURCE_MODELS` `("tables.KeyValueTable","name")`; `IMPORTED_ENTITIES[KEY_VALUE_TABLE] = (KEY_VALUE_TABLE,"name")`; `ACCESS_RESOURCE_TYPES = {"flow": FLOW, "key_value_table": KEY_VALUE_TABLE}` |
| A6 | `plugins/manifest.py` | bridge `{1,2}`; `AccessEntry.type`/actions per §1.1 (`ACCESS_ACTIONS_BY_TYPE`, `ACCESS_ENTITY_TYPES`); refs by type (`:396-397`); KV node table check next to `_check_flows` (`:409-422`); `UI_CONTENT_TYPES` + limits (`:41-52`); `PluginPackage.key_value_table_name()` (next to `secret_name`, `:218-224`); `load_package` returns `resources` with KV names already prefixed (preview, conflicts, install all see the final name) |
| A7 | `plugins/services/bundle_reader.py:16-18` | 30 MB / 400 / 60 MB |
| A8 | `plugins/services/install_checks.py:31-75` | KV conflicts iexact; KV node mode perms (reuse `MODE_PERMISSIONS`) into `missing_permissions` |
| A9 | `plugins/services/preview.py:44,58-68`, `presenter.py:69-80` | Resolve access names/ids per type via `ACCESS_RESOURCE_TYPES` |
| A10 | `plugins/services/lifecycle_service.py:42-56,79-108,199-208` | `KEY_VALUE_TABLE` in `DELETE_ORDER` after `FLOW`; delete via `KeyValueTableService().delete_table()` if still present; `_ExternalUsage(KEY_VALUE_TABLE, "tables.KeyValueNode", "key_value_table", FLOW, "graph")` |
| A11 | `plugins/services/guard.py` + `tables/services/converter_service.py:856-866` | `check_key_value_table(table_id)`: an org flow using a suspended plugin's table fails at session build like tools (`converter_service.py:258-262`) |
| A12 | `plugins/asset_views.py:17-32`, `plugins/services/ui_token.py:15` | CSP + CORS §1.4; 43200 s |
| A13 | `django_app/settings/base.py` (`PLUGINS_DEV_MODE = env.bool(…, default=False)`), `src/docker-compose.yaml:69-120` (`PLUGINS_DEV_MODE: ${PLUGINS_DEV_MODE:-false}`), `src/env.yaml` (entry, default false) | Instance flag |
| A14 | `plugins/models.py` (`dev_ui_url` CharField(255, blank, default ""), `dev_ui_user` FK user null SET_NULL `related_name="+"`); migration via `make -C <SRC> django-makemigrations ARGS="plugins"` | Model + migration |
| A15 | new `plugins/services/dev_ui_service.py` (validate/set/clear/`dev_url_for(plugin,user)`); `plugins/exceptions.py` (`PluginDevModeDisabledError` 409); `plugins/serializers.py`; `plugins/views.py:38-49` (`"dev_ui": Permission.UPDATE`, POST+DELETE action); `ui_service.py:30-66` (dev branch §1.3); `presenter.py` (3 fields) | Dev mode |
| A16 | `plugins/management/commands/plugin_export_resources.py` | `--sample {chat-bot,chat-admin}`; `chat-admin` builds in a rolled-back transaction: LLMModel `gpt-4o-mini` (catalog) + LLMConfig; AgentDefinition; KeyValueTable `conversations`; Graph "Chat Admin": Start `{conversation_id:"", question:""}` → KV read `[{key:"{variables.conversation_id}", value:"variables.conversation"}]` → TaskNode "Answer" (input question, conversation) → PythonNode "Append turn" (conversation_id, conversation, question, answer → §1.6 record with size cap) → KV write `[{key:"{variables.conversation_id}", value:"variables.record"}]` → End `{answer, conversation_id}`; prints refs. Missing-key read → None (crew `key_value_node.py:53`); write refuses null (`:155-157`). Check how a task renders a dict/None in `{conversation}` (`crew/services/graph/nodes/instruction_render.py`); if ugly add a "Format history" Python node before the task |
| A17 | Tests | §4.1 |

### (B) `angular-dev` — EpicStaff host (`frontend/src/app/…`)
| # | File(s) | Change |
|---|---|---|
| B1 | `features/plugins/models/plugin.model.ts:10-26,158-164,254-270` | Unions + `key_value_table` (also missing `llm_model`/`embedding_model`); `read`; `PluginUiSession.dev_mode`, `expires_in: number\|null`; `dev_*` fields; conflict type; `plugin_dev_mode_disabled` |
| B2 | `bridge/access-policy.ts:4,31-46` | `ACCESS_TYPES_BY_VERSION = {1:{flow:[…]}, 2:{flow:[…], key_value_table:['read']}}`; `buildAccessPolicy(entries, version)`; v1 unchanged (ignores KV) |
| B3 | `bridge/bridge-protocol.ts` | v2 topics + types (`subscription: string\|null`), `BridgeInitContextV2`, nav limit; v1 constants untouched |
| B4 | new `bridge/v2/bridge-v2.methods.ts`; `bridge/bridge-tables.ts:5` → `{1:V1, 2:V2}` | v2 reuses v1 handlers + own `bridge.hello` + `kv.list`, `kv.get`, `nav.changed` |
| B5 | `bridge/plugin-bridge-api.service.ts` | `listKeyValueEntries`, `findKeyValueEntryId(table,key)`, `getKeyValueEntry(id)` with `bridgeContext()` (`:66-68`) |
| B6 | `bridge/bridge-method.ts:8-25`, `bridge/plugin-bridge-host.service.ts` | `attach(frame, session, {initialPath, devMode, onNavChanged})`; v2 init (nav, theme); `postHostEvent(topic,data)` with `subscription:null`; `notifyNavigation(path)`; theme effect; nav rate limit; **dev**: 2nd `ready` resets (close port/streams/pending, clear own sessions) + re-handshake, ignore `onFrameLoad` after the first; production still tears down on 2nd load (`:149-157`) |
| B7 | new `bridge/plugin-nav-path.util.ts` | grammar §1.5 → `{segments, queryParams}`; canonical path ⇄ router |
| B8 | new `services/plugin-host-theme.service.ts` (root) | token map §1.5, MutationObserver on html/body `class`, `theme` signal |
| B9 | `app.routes.ts:196-203` | replace `plugins/:id` with a `UrlMatcher` consuming `plugins/<id>/**` (posParam `id`) |
| B10 | `pages/plugin-host-page/*` (`.ts:76-80,124-146`, `.html:4-13`) | (a) initial path from consumed segments+query → iframe `#path` + attach opts; (b) `nav.changed` → `router.navigate(['/plugins', id, ...segments], {queryParams, replaceUrl})`, remember canonical path; (c) route change for same id with different canonical path → `bridgeHost.notifyNavigation`; (d) dev: validate with new `toPluginDevFrameUrl` (`utils/plugin-frame-url.util.ts`), DEV banner (URL, "only you see this", Reload) |
| B11 | `layouts/main-layout/sidenav/sidenav.component.ts:315-322` | plugin button stays active on deep links (`routerLinkActive` exactness) |
| B12 | `services/plugins-api.service.ts`, `services/plugins-store.service.ts`, `components/plugins-section/*` | `setDevUi`/`clearDevUi`; "Dev mode" control only when `dev_mode_available` + `plugins:update`; DEV badge when `dev_ui_url` set |
| B13 | `utils/plugin-display.util.ts:17,80-92`, install/delete dialogs, `plugin-install-dialog.component.ts:39,281` | label "Key-value table"; access line "Read key-value table '…'"; conflicts; 30 MB |
| B14 | specs | §4.1 |

### (C) SDK + CLI — new top-level `plugin-sdk/` (TypeScript, outside `frontend/`: no frontend lint/notices; not in any Docker context; pre-commit is py/yaml only)
| # | File(s) | Content |
|---|---|---|
| C1 | `package.json` (`@epicstaff/plugin-sdk`, private, `type: module`, exports `.` + `./storage-shim`, `bin: epicstaff-plugin`), `tsconfig.json` (strict, ES2022+DOM), `README.md` (author guide incl. Angular/Vite build settings + sandbox rules table) | scaffold |
| C2 | `src/protocol.ts` | §1.5 types |
| C3 | `src/client.ts` | `connect({timeoutMs, mock, navSync = true, theme = true})` → `EpicStaffBridge {context, call, on, flows.run, flows.runAndWait (run→subscribe→resolve on `graph_end` `end_node_result`, reject on failed status / closed without answer), sessions.*, kv.list, kv.get, nav, theme}`; `BridgeCallError {code}`; nav reports before handshake queued (latest wins) |
| C4 | `src/storage-shim.ts` | in-memory local/sessionStorage (only where access throws by default; `force` option); `document.cookie` stub |
| C5 | `src/nav-sync.ts` | patch `history.pushState` → `replaceState` + `nav.changed {replace:false}`; `replaceState` → `{replace:true}`; on `nav.navigate`: `replaceState('#'+path)` + synthetic `popstate`/`hashchange` (or custom `navigate` callback) |
| C6 | `src/theme.ts` | set `--es-*` on `<html>` + `data-es-theme` + `color-scheme`; follow `theme.changed` |
| C7 | `src/mock-host.ts` | `createMockHost({access, flows:{alias:(variables)=>output}, kvTables:{alias: entries}})` over a MessageChannel, used when not framed |
| C8 | `bin/epicstaff-plugin.mjs` | `validate <dir> [--ui <dir>]` mirrors §1.1/§1.4 (server authoritative) + HTML lint (inline `<script>`, `on*=`, `<base`, `javascript:`); `pack <dir> --ui <dir> --out <zip>` (no dir entries, stable order, dependency-free zip writer: `node:zlib` deflateRawSync + crc32; local Node v24.3) |
| C9 | `test/*.test.ts` (`node --test`) | §4.1 |

### (D) Chat Admin sample — new top-level `plugin-samples/chat-admin/`
- **D1 `plugin/`:** `resources.json` generated by A16; `plugin.json` — `bridge: 2`, `id: chat-admin`, `icon: ui/icon.svg`,
  `ui.entry: ui/index.html`, slot `OPENAI_API_KEY` bound to the LLMConfig ref; access `chat` (flow: run,
  sessions.read, sessions.stop) + `conversations` (key_value_table: read) — refs from the command output.
- **D2 `app/`:** Angular **22.2.1** (= `frontend/package.json:38`), TS ~6.0.3, zoneless,
  `provideRouter(routes, withHashLocation(), withComponentInputBinding())`; SDK `file:../../../plugin-sdk`;
  `@fontsource/inter` (proves fonts); `main.ts` imports `@epicstaff/plugin-sdk/storage-shim` first; `connect()` in
  `provideAppInitializer` (nav sync before first navigation). Screens: `/chat` + `/chat/:id` (continue via `kv.get`; ask
  via `flows.runAndWait('chat', {conversation_id, question})`), `/conversations` (lazy; search/sort/page in query
  params), `/conversations/:key` (lazy; transcript), `/about` (lazy). Styles `var(--es-*, fallback)`. `public/icon.svg`.
  `angular.json` production: `optimization.styles.inlineCritical: false`, `fonts: false`, `outputHashing: all`,
  `sourceMap: false`, no `baseHref`, no `<base>`. Dev server `port: 4300`, `headers: {"Access-Control-Allow-Origin":"*"}`.
  Mock host when not framed.
- **D3 pack:** `npm run build` → `epicstaff-plugin pack ../plugin --ui dist/chat-admin/browser --out <abs zip>`.
- **D4** `plugin-samples/chat-admin/README.md`.

### Adding the next family member
- Access/resource type: export entity (new-import-export) → `PluginResourceType`+`RESOURCE_MODELS`+`IMPORTED_ENTITIES`
  (+ choice migration) → `ACCESS_ENTITY_TYPES`/`ACCESS_ACTIONS_BY_TYPE` + `ACCESS_RESOURCE_TYPES` → `DELETE_ORDER`
  (+ branch) + `EXTERNAL_USAGES` → guard hook if runnable → frontend unions/labels → `ACCESS_TYPES_BY_VERSION[n]` →
  methods in a new bridge table → SDK types + CLI validator.
- Bridge version: new `bridge/vN/` table + `BRIDGE_TABLES` + `SUPPORTED_BRIDGE_VERSIONS` + contract spec + SDK protocol.

## 3. Parallelism
A, B, C start together. D2 starts once C2/C3 signatures exist. A1 → A16 → D1. A6/A12 + C8 → D3. A + B + D3 → e2e.
Inside B: B9/B10 depend on B6/B7; B6 on B2–B5.

## 4. Verification

### 4.1 Tests (each must fail without its change)
- `src/django_app/tests/import_export_tests/test_key_value_table_import_export.py` (new): flow export has `KeyValueTable`
  (no entries); import into a clean org creates + binds via IDMapper; same-name (iexact) table in the importing org
  reused; **another org's same-name table never reused**; legacy file without the entity keeps by-name binding;
  importer without `key_value_tables:create` → 403; `IMPORT_VERSION == 3`.
- `tests/services_tests/test_key_value_node_copy_import.py` (extend): partial export has no `KeyValueTable`.
- `tests/api_tests/test_key_value_tables_api.py` (extend): `?table=&key=` exact; foreign table id → empty.
- `tests/plugins_tests/test_plugin_key_value_tables.py` (new): install force-creates `chat_admin__conversations` even
  if the org has `conversations`; registry row; node bound. Existing `CHAT_ADMIN__CONVERSATIONS` → 409
  `plugin_resource_conflict`. Missing `key_value_tables` create/update → 403 `plugin_install_forbidden` before any
  write. Inspect contents/access/conflicts. Manifest rejections: KV access with bridge 1; `run` on KV; ref not a
  KeyValueTable; **KV node naming an unshipped table**; prefixed name > 255. Access resolution: detail + ui-session KV
  entries carry `resource_id`/`resource_name`; deleted table → `null`.
- `test_plugin_lifecycle.py` (extend): delete removes table + rows; org flow's KV node unlinked + in
  `external_usages`; delete needs `key_value_tables:delete`. `test_plugin_guard.py`: suspend → org flow using the
  table refused at session build.
- `test_plugin_permissions.py`: other org's `dev-ui` / `ui-session` → 404.
- `test_plugin_ui_assets.py` (update): exact CSP; `Access-Control-Allow-Origin: *`; every new extension's type
  (parametrized); 12 h boundary; 300-file / 20 MB caps (`test_plugin_install.py`); bundle caps.
- `tests/plugins_tests/test_plugin_dev_mode.py` (new): flag off → 409; URL allow/deny (https, `localhost.evil.com`,
  userinfo, query, fragment); Member → 403; dev URL returned only to `dev_ui_user` and only while flag on; DELETE
  clears; list/detail fields.
- `tests/graph_versioning_tests/`: still green (`manager.py:337-363` ignores unknown types).
- Frontend: `bridge/v1/bridge-v1.contract.spec.ts` **unchanged and passing** + an `access-policy.spec.ts` case (v1 drops
  KV); new `bridge/v2/bridge-v2.contract.spec.ts` (method/param/result keys; exact KV URLs + query; ids stripped;
  table mismatch → `not_found`; bad key → `bad_request` no HTTP; wrong type/action → `forbidden` no HTTP; nav grammar
  + rate limit; init v2 shape; `theme.changed`/`nav.navigate` with `subscription: null`);
  `plugin-bridge-host.service.spec.ts` (dev re-handshake on 2nd `ready`; production ignores 2nd `ready`, tears down on
  2nd `load`); `plugin-host-page.component.spec.ts`, `plugin-frame-url.util.spec.ts`, `plugin-nav-path.util.spec.ts`,
  `plugin-host-theme.service.spec.ts` (deep link → `#path` + init; no echo loop; dev URL validation; banner; theme).
- SDK `plugin-sdk/test/*.test.ts`: handshake/timeout; `runAndWait`; storage shim; pushState → replaceState + report;
  `pack` output readable by Python `zipfile`; `validate` rejects §1.1 cases.

### 4.2 Commands
```
make -C <SRC> django-makemigrations ARGS="plugins"
make -C <SRC> django-tests ARGS="tests/plugins_tests tests/import_export_tests tests/services_tests/test_key_value_node_copy_import.py tests/services_tests/test_key_value_table_service.py tests/api_tests/test_key_value_tables_api.py tests/graph_versioning_tests -q"
npm --prefix <SRC>/frontend run build && npm --prefix <SRC>/frontend run lint && npm --prefix <SRC>/frontend run format:check
node <SRC>/scripts/check-undeclared-imports.mjs && node <SRC>/scripts/check-third-party-notices.mjs
npm --prefix <SRC>/frontend test -- --watch=false
npm --prefix <SRC>/plugin-sdk install && npm --prefix <SRC>/plugin-sdk run build && npm --prefix <SRC>/plugin-sdk test
```

### 4.3 Sample zip
```
make -C <SRC> django-manage CMD="plugin_export_resources --sample chat-admin --output ../../plugin-samples/chat-admin/plugin/resources.json"
npm --prefix <SRC>/plugin-samples/chat-admin/app install && npm --prefix <SRC>/plugin-samples/chat-admin/app run build
node <SRC>/plugin-sdk/bin/epicstaff-plugin.mjs pack <SRC>/plugin-samples/chat-admin/plugin --ui <SRC>/plugin-samples/chat-admin/app/dist/chat-admin/browser --out /Users/ihorpolishchuk/Projects/EpicStaff/FRONT/chat-admin-plugin.zip
```

### 4.4 Docker (only `django_app` + `frontend` change; migrations run in `entrypoint.sh:12`)
```
IMAGE_TAG=plugins-proto docker compose -f <SRC>/src/docker-compose.yaml --project-directory <SRC>/src build django_app frontend
IMAGE_TAG=plugins-proto docker compose -f <SRC>/src/docker-compose.yaml --project-directory <SRC>/src up -d django_app frontend
PLUGINS_DEV_MODE=true IMAGE_TAG=plugins-proto docker compose … up -d django_app   # dev mode
```

### 4.5 End-to-end smoke
1. Install `chat-admin-plugin.zip`: review lists flow, agent, LLM config, secret `CHAT_ADMIN__OPENAI_API_KEY`, table
   `chat_admin__conversations`, access "Read key-value table …", Python code warning → Ready.
2. KV page shows the empty table. 3. Nav icon → app in content area; no CSP errors; `main-*.js`, `chunk-*.js`,
   `*.woff2` load with ACAO `*`. 4. Chat twice → one `c_…` row with the §1.6 record. 5. Conversations list/search/sort/page.
6. Detail URL `/plugins/<id>/conversations/c_…`; refresh restores; Back/Forward one step each; sidenav icon → app home.
7. `document.body.classList.add('my-app-light')` → app recolours live. 8. In-frame `fetch('/api/plugins/')` blocked.
9. v1 `chat-bot-plugin.zip` still installs and chats. 10. Suspend/resume; org flow on the table refused while suspended.
11. Dev mode (`npm start` in `app/`, port 4300): set URL → DEV banner, real data, live reload reconnects; other admin
   sees production; flag off → control hidden, production app. 12. Delete preview + delete; other org 404.

### 4.6 Review gates
`/rbac-coverage` for the `dev-ui` action; migration reviewed; `IMPORT_VERSION` untouched; then
`backend-code-reviewer`, `frontend-code-reviewer`, `security-reviewer` last (CORS `*`, 12 h token, by-name rebinding
block, `kv.get` table pinning, nav path → router commands, dev URL + per-user binding).

## 5. Risks (with defaults)
1. Angular dev server from an opaque origin (does `headers` cover Vite responses; live-reload websocket with
   `Origin: null`) — default `headers` + banner Reload; fallback `ng build --watch` + static CORS server on 4300.
2. Frameworks setting `location.hash` directly add frame history entries — document "use a pushState-based hash router".
3. Chrome Local Network Access may block a localhost dev iframe when EpicStaff is not on localhost — dev mode documented for local stacks.
4. Plain flow imports now create the referenced table (needs `key_value_tables:create`, else whole import 403) — accepted.
5. Route keeps the DB id (`/plugins/7/conversations/c_…`), not the slug — accepted; slug later.
6. Dev URL is per user (the admin who set it).
7. 12 h token: an app open > 12 h can't fetch a not-yet-loaded lazy chunk — accepted; SDK hints reload.
8. Light mode not triggerable from EpicStaff UI today — detection shipped; devtools test.
9. While suspended the plugin's table is still readable via EpicStaff's own KV pages — accepted, documented.
10. The sample needs the sandbox service (Python node) and a real OpenAI key for e2e.
11. `{conversation}` rendering of a dict/None in the task prompt — verify in A16.
12. Existing tests asserting the graph dependency dict / old CSP string will fail by design — update, don't loosen.
