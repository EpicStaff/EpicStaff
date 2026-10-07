---
id: plugins-code-map
title: Plugins — code map
type: code-map
status: draft
tags: [plugins, prototype, code-map]
created: 2026-10-07
updated: 2026-10-07
related: [plugins-architecture, plugin-package-format, plugin-bridge-v1, plugin-bridge-v2, plugin-author-tooling, plugins-api-contract, plugins-rules, plugins-glossary, plugins-prd, plugin-apps-plan, plugin-apps-status, alignment-plugin-apps]
topic: plugins
aliases: [plugin, plugins, plugin apps, plugin host, plugin page, plugin bridge, bridge v1, bridge v2, plugin sdk, epicstaff-plugin cli, plugin.json, resources.json, ui-session, plugin-ui token, dev mode, PLUGINS_DEV_MODE, chat-admin, chat-bot sample, PluginResource, plugin guard, suspend plugin]
last-mapped: 2026-10-07
mapped-by: claude (architect, worktree pinned to proto/plugins-06-10-26 @ bfeea626f)
maps:
  - docs/proto/plugins/
  - src/django_app/plugins/
  - src/django_app/plugins/models.py
  - src/django_app/plugins/migrations/0001_initial.py
  - src/django_app/plugins/migrations/0002_dev_ui_and_key_value_tables.py
  - src/django_app/plugins/resource_types.py
  - src/django_app/plugins/manifest.py
  - src/django_app/plugins/exceptions.py
  - src/django_app/plugins/serializers.py
  - src/django_app/plugins/views.py
  - src/django_app/plugins/urls.py
  - src/django_app/plugins/apps.py
  - src/django_app/plugins/asset_views.py
  - src/django_app/plugins/services/bundle_reader.py
  - src/django_app/plugins/services/install_service.py
  - src/django_app/plugins/services/install_checks.py
  - src/django_app/plugins/services/permission_checks.py
  - src/django_app/plugins/services/preview.py
  - src/django_app/plugins/services/presenter.py
  - src/django_app/plugins/services/lifecycle_service.py
  - src/django_app/plugins/services/guard.py
  - src/django_app/plugins/services/ui_service.py
  - src/django_app/plugins/services/ui_token.py
  - src/django_app/plugins/services/dev_ui_service.py
  - src/django_app/plugins/services/knowledge_service.py
  - src/django_app/plugins/services/secret_slot_service.py
  - src/django_app/plugins/services/secret_destinations.py
  - src/django_app/plugins/management/commands/plugin_export_resources.py
  - src/django_app/plugins/samples/chat-bot/
  - src/django_app/plugins/samples/chat-bot/ui/bridge-client.js
  - src/django_app/plugins/samples/chat_admin_code/
  - src/django_app/plugins/samples/chat_admin_code/append_turn.py
  - src/django_app/plugins/samples/chat_admin_code/format_history.py
  - src/django_app/plugins/samples/zip_builder.py
  - src/django_app/django_app/settings/base.py
  - src/django_app/django_app/urls.py
  - src/django_app/rbac/access/catalog.py
  - src/django_app/rbac/access/effective.py
  - src/django_app/rbac/access/builtin_roles.json
  - src/django_app/rbac/models/enums.py
  - src/django_app/rbac/migrations/0004_plugins_resource_type.py
  - src/django_app/tables/views/views.py
  - src/django_app/tables/services/session_manager_service.py
  - src/django_app/tables/services/converter_service.py
  - src/django_app/tables/services/base_node_payload_service.py
  - src/django_app/tables/services/key_value_table_service.py
  - src/django_app/tables/views/model_view_sets.py
  - src/django_app/tables/import_export/enums.py
  - src/django_app/tables/import_export/constants.py
  - src/django_app/tables/import_export/permissions.py
  - src/django_app/tables/import_export/schemas.py
  - src/django_app/tables/import_export/strategies/base.py
  - src/django_app/tables/import_export/services/import_service.py
  - src/django_app/tables/import_export/serializers/key_value_table.py
  - src/django_app/tables/import_export/strategies/key_value_table.py
  - src/django_app/tables/import_export/strategies/graph.py
  - src/django_app/tables/import_export/strategies/nodes/key_value_node.py
  - src/django_app/tables/apps.py
  - src/crew/clients/key_value.py
  - src/shared/envtools.py
  - src/sandbox/dynamic_venv_executor_chain.py
  - src/docker-compose.yaml
  - src/env.yaml
  - src/.env.example
  - src/nginx/templates/default.conf.template
  - src/django_app/tests/plugins_tests/
  - src/django_app/tests/plugins_tests/conftest.py
  - src/django_app/tests/plugins_tests/helpers.py
  - src/django_app/tests/plugins_tests/test_chat_admin_sample.py
  - src/django_app/tests/import_export_tests/test_key_value_table_import_export.py
  - src/django_app/tests/import_export_tests/test_import_force_create.py
  - src/django_app/tests/services_tests/test_key_value_node_copy_import.py
  - src/django_app/tests/api_tests/test_key_value_tables_api.py
  - src/crew/tests/clients/test_key_value_client.py
  - frontend/src/app/features/plugins/
  - frontend/src/app/features/plugins/models/plugin.model.ts
  - frontend/src/app/features/plugins/plugins.providers.ts
  - frontend/src/app/features/plugins/services/plugins-api.service.ts
  - frontend/src/app/features/plugins/services/plugins-store.service.ts
  - frontend/src/app/features/plugins/services/plugin-host-theme.service.ts
  - frontend/src/app/features/plugins/components/plugins-section/
  - frontend/src/app/features/plugins/components/plugin-install-dialog/
  - frontend/src/app/features/plugins/components/plugin-secrets-dialog/
  - frontend/src/app/features/plugins/components/plugin-secret-destinations/
  - frontend/src/app/features/plugins/components/plugin-dev-mode-dialog/
  - frontend/src/app/features/plugins/components/plugin-delete-dialog/
  - frontend/src/app/features/plugins/pages/plugin-host-page/plugin-host-page.component.ts
  - frontend/src/app/features/plugins/pages/plugin-host-page/plugin-host-page.component.html
  - frontend/src/app/features/plugins/pages/plugin-host-page/plugin-page.matcher.ts
  - frontend/src/app/features/plugins/bridge/bridge-protocol.ts
  - frontend/src/app/features/plugins/bridge/bridge-method.ts
  - frontend/src/app/features/plugins/bridge/bridge-tables.ts
  - frontend/src/app/features/plugins/bridge/access-policy.ts
  - frontend/src/app/features/plugins/bridge/plugin-bridge-host.service.ts
  - frontend/src/app/features/plugins/bridge/plugin-bridge-api.service.ts
  - frontend/src/app/features/plugins/bridge/plugin-session-stream.ts
  - frontend/src/app/features/plugins/bridge/plugin-nav-path.util.ts
  - frontend/src/app/features/plugins/bridge/v1/bridge-v1.methods.ts
  - frontend/src/app/features/plugins/bridge/v1/bridge-v1.contract.spec.ts
  - frontend/src/app/features/plugins/bridge/v2/bridge-v2.methods.ts
  - frontend/src/app/features/plugins/bridge/v2/bridge-v2.contract.spec.ts
  - frontend/src/app/features/plugins/bridge/testing/bridge-test-harness.ts
  - frontend/src/app/features/plugins/utils/plugin-display.util.ts
  - frontend/src/app/features/plugins/utils/plugin-frame-url.util.ts
  - frontend/src/app/features/plugins/utils/plugin-error.util.ts
  - frontend/src/app/features/plugins/utils/plugin-secret-value.util.ts
  - frontend/src/app/app.routes.ts
  - frontend/src/app/app.config.ts
  - frontend/src/app/layouts/main-layout/sidenav/sidenav.component.ts
  - frontend/src/app/layouts/main-layout/sidenav/sidenav.component.html
  - frontend/src/app/features/configure-models/components/configure-models-dialog/configure-models-dialog.component.ts
  - frontend/src/app/features/configure-models/components/configure-models-dialog/configure-models-dialog.component.html
  - frontend/src/app/features/configure-models/enums/configure-models-tab-id.enum.ts
  - frontend/src/app/services/auth/permissions.service.ts
  - frontend/src/app/shared/models/role-based-access/permissions.model.ts
  - frontend/src/app/core/interceptors/forbidden.interceptor.ts
  - frontend/src/app/core/interceptors/skip-forbidden-reload.context.ts
  - frontend/src/app/services/auth/sse-ticket.service.ts
  - frontend/src/styles/_variables.scss
  - plugin-sdk/
  - plugin-sdk/package.json
  - plugin-sdk/README.md
  - plugin-sdk/src/index.ts
  - plugin-sdk/src/client.ts
  - plugin-sdk/src/connection.ts
  - plugin-sdk/src/protocol.ts
  - plugin-sdk/src/run-and-wait.ts
  - plugin-sdk/src/nav-sync.ts
  - plugin-sdk/src/nav-path.ts
  - plugin-sdk/src/theme.ts
  - plugin-sdk/src/storage-shim.ts
  - plugin-sdk/src/storage.ts
  - plugin-sdk/src/mock-host.ts
  - plugin-sdk/src/errors.ts
  - plugin-sdk/src/report-error.ts
  - plugin-sdk/bin/epicstaff-plugin.mjs
  - plugin-sdk/cli/
  - plugin-sdk/cli/rules.mjs
  - plugin-sdk/cli/validate.mjs
  - plugin-sdk/cli/html-lint.mjs
  - plugin-sdk/cli/bundle-files.mjs
  - plugin-sdk/cli/pack.mjs
  - plugin-sdk/cli/zip.mjs
  - plugin-sdk/test/
  - plugin-samples/chat-admin/
  - plugin-samples/chat-admin/README.md
  - plugin-samples/chat-admin/plugin/plugin.json
  - plugin-samples/chat-admin/plugin/resources.json
  - plugin-samples/chat-admin/app/package.json
  - plugin-samples/chat-admin/app/angular.json
  - plugin-samples/chat-admin/app/src/main.ts
  - plugin-samples/chat-admin/app/src/app/app.config.ts
  - plugin-samples/chat-admin/app/src/app/app.routes.ts
  - plugin-samples/chat-admin/app/src/app/core/plugin-bridge.service.ts
  - plugin-samples/chat-admin/app/src/app/conversations/conversations-api.service.ts
  - plugin-samples/chat-admin/app/src/app/mock/chat-admin-mock-host.ts
contracts:
  - plugin-package-contract
  - bridge-version-freeze
  - plugin-page-sandbox
  - plugin-effective-access
  - plugin-deep-link-path
  - plugin-dev-mode-guard
  - plugin-key-value-table-export
  - sdk-host-protocol-mirror
related-skills: [/new-import-export, /rbac-coverage, /choosing-django-tests, /proto-page]
related-agents: [architect, backend-dev, angular-dev, backend-code-reviewer, frontend-code-reviewer, security-reviewer]
---

# Plugins — code map

> **Prototype branch only (`proto/plugins-06-10-26`).** `src/django_app/plugins/`, `frontend/src/app/features/plugins/`, `plugin-sdk/`, `plugin-samples/`, `docs/proto/plugins/` and the new import/export KV files do not exist on `developer` or `main`. The shared files listed here (`tables/`, `rbac/`, settings, compose, sidenav, routes) do exist on `developer`, but without the plugin changes this page describes.

A **plugin** is an uploaded zip. Installing it creates ordinary, editable org rows: a flow, plus agents, configs, key-value tables, secrets, knowledge and files. It creates them through the import/export machinery and records each one in `PluginResource`, so that suspend and delete can find them later. A plugin can also ship its own web page. That page is stored in the database, served into a sandboxed iframe inside EpicStaff's shell, and talks to EpicStaff only through a versioned `postMessage` bridge run by the host page. The bridge acts as the signed-in user, narrowed by the plugin's access list. `plugin-sdk/` (client and CLI) is for plugin authors, and `plugin-samples/chat-admin/` is the reference bridge-v2 app. For C4 diagrams and key decisions, see [[plugins-architecture]] and, for the plugin side, [[plugin-author-tooling]]. This page covers paths, roles, contracts and the ways things break.

---

## TL;DR for agents starting plugin work

1. **The plugin is a resource, not an identity.** What it installs is normal org data. The plugin owns it only through `PluginResource` rows (`resource_type` + `object_id` + `manifest_ref`). There is no foreign key and no ContentType. If a row gets a new primary key, the plugin silently loses track of it.
2. **The feature has two halves that meet at one endpoint.**
   - **Install** (Django): `manifest.py` → `install_service.py` → `ImportService` with `force_create_types`.
   - **Page** (frontend): `PluginHostPageComponent` + `PluginBridgeHost`.
   - The two meet at `POST /api/plugins/{id}/ui-session/`. **The server never sees the bridge.** The access list is enforced only in the browser host. The sandbox is what forces every call through that host.
3. **Bridge versions are frozen.** New behaviour means a new `bridge/vN/` table. v1 never changes, and the `chat-bot` sample still speaks v1.
4. **Most of this feature is security surface:** iframe attributes, asset CSP and headers, the Fetch-Metadata refusal, the page token, the handshake origin check, dev mode and the access policy. Any change to them ends with `security-reviewer`.
5. **The plugin types form a family:** resource types, access types and bridge versions. Follow "Adding the next family member" below. Most of the registries are test-enforced. `DELETE_ORDER` is **not**.
6. **Agents:**
   - `backend-dev`: `src/django_app/plugins/` plus the touched `tables/` and `rbac/` files.
   - `angular-dev`: `frontend/src/app/features/plugins/`. **Not** `flow-editor-dev`.
   - `plugin-sdk/` and `plugin-samples/` (TypeScript outside `frontend/`) have no owning specialist. `angular-dev` is the closest fit.
   - Tests: `make -C <SRC> django-tests ARGS="tests/plugins_tests …"`, `npm --prefix <SRC>/frontend test`, `npm --prefix <SRC>/plugin-sdk test`.

---

## Code map

### Layer 1 — Django `plugins` app (`src/django_app/plugins/`)

**Model and registries**

| File | Role |
|---|---|
| `src/django_app/plugins/models.py` | `Plugin` (OrgScopedModel, `unique(org, plugin_id)`). Fields: `state` preparing/ready/needs_attention, a separate `suspended` flag, JSON copies of `access`, `secret_slots` and `manifest`, plus `dev_ui_url` + `dev_ui_user`. `PluginResource` is the registry. `PluginAsset` holds the page files as DB blobs with a sha256. |
| `src/django_app/plugins/migrations/0001_initial.py` | Creates the three tables. Depends on `rbac.0004_plugins_resource_type`. |
| `src/django_app/plugins/migrations/0002_dev_ui_and_key_value_tables.py` | Adds `dev_ui_url` and `dev_ui_user`, and adds `key_value_table` to the `PluginResource.resource_type` choices. |
| `src/django_app/plugins/resource_types.py` | Every registry table:<br>• `PluginResourceType` — stored values, never rename.<br>• `RESOURCE_MODELS` — model label, display column, org column.<br>• `IMPORTED_ENTITIES` / `PLUGIN_OWNED_TYPES` — force-created and registered.<br>• `CREATED_CATALOG_ENTITIES` — LLM/embedding models, linked only when the import created an org-owned row.<br>• `ACCESS_RESOURCE_TYPES` — access `type` → resource type.<br>• `RBAC_RESOURCE_TYPES` — derived gate per row type.<br>• `CATALOG_TYPES` — referenced, never owned. |
| `src/django_app/plugins/exceptions.py` | Every API error with a stable `code`:<br>• 400 `invalid_plugin` (list of `{loc, message}`), `invalid_plugin_secrets`, dev URL `invalid`<br>• 409 `plugin_already_installed`, `plugin_resource_conflict`, `plugin_suspended`, `plugin_not_ready`, `plugin_has_no_ui`, `plugin_not_retryable`, `plugin_dev_mode_disabled`<br>• 403 `plugin_install_forbidden`, `plugin_delete_forbidden` |
| `src/django_app/plugins/apps.py` | Registers `plugins.Plugin` in the org-delete report. |

**Package format (install time)**

| File | Role |
|---|---|
| `src/django_app/plugins/services/bundle_reader.py` | `read_bundle()`:<br>• caps the zip at 30 MB / 400 entries / 60 MB unpacked (storage `ArchiveExtractionGuard`)<br>• drops `__MACOSX` and `.DS_Store`<br>• strips one wrapping folder<br>• returns `PluginBundle` |
| `src/django_app/plugins/manifest.py` | `load_package()` is the only entry point.<br>• Pydantic `PluginManifest` (`extra="forbid"`).<br>• `SUPPORTED_FORMAT_VERSIONS={1}`, `SUPPORTED_BRIDGE_VERSIONS={1,2}`.<br>• Access tables: `ACCESS_ACTIONS_BY_TYPE`, `ACCESS_ENTITY_TYPES`, `ACCESS_MIN_BRIDGE_VERSION`.<br>• `SECRET_BINDING_FIELDS`.<br>• `UI_CONTENT_TYPES` — also the served Content-Types.<br>• Caps: UI ≤ 300 files / 20 MB, icon ≤ 64 KB.<br>• Checks layout, entity types, refs, KV tables, KV nodes, name-bound secrets, knowledge, storage files.<br>• Helpers: `slot_secret_name()`, `key_value_table_name()`, `_with_installed_table_names()`. |
| `src/django_app/plugins/services/install_checks.py` | Shared by preview and install:<br>• `reject_if_installed` — no in-place upgrade.<br>• `missing_permissions` — create on every contained type, plus KV node mode permissions via `MODE_PERMISSIONS`.<br>• `find_conflicts` — secret name, KV table name (iexact), storage path.<br>• `check_secret_values` — ≤ 4096 chars. |
| `src/django_app/plugins/services/permission_checks.py` | `missing_permissions_on(types, action, effective)`: `plugins:<action>` plus the RBAC type of each row type. Install and delete use the same shape. |
| `src/django_app/plugins/services/preview.py` | `build_preview()` builds the inspect response: contents, access with installed names, slots with destinations, code review items, warnings (UI / Python code / knowledge), `can_install`. |
| `src/django_app/plugins/services/secret_destinations.py` | The host each slot value will be sent to, for both the bundle and installed rows. |

**Services**

| File | Role |
|---|---|
| `src/django_app/plugins/services/install_service.py` | `PluginInstallService.inspect/install`. `_PluginInstallation.run()` runs in one transaction:<br>1. `Plugin` row<br>2. slot secrets<br>3. `ImportService(... ImportSettings(force_create_types=PLUGIN_OWNED_TYPES))`<br>4. register created ids<br>5. bind secrets by FK<br>6. knowledge collections<br>7. storage files (deleted again on failure)<br>8. `PluginAsset` rows<br>9. `on_commit` → start indexing |
| `src/django_app/plugins/services/lifecycle_service.py` | `suspend`: flag, then stops live sessions after commit. `resume`. `delete_preview`. `delete`: checks permissions twice, suspends first, walks `DELETE_ORDER` (KV tables go through `KeyValueTableService.delete_table`), deletes storage objects after commit. `EXTERNAL_USAGES` lists org rows that lose a plugin row. |
| `src/django_app/plugins/services/guard.py` | `plugin_guard` raises `PluginSuspendedError` from:<br>• `check_flow` — includes transitive subflows<br>• `check_agent_definition`<br>• `check_tool`<br>• `check_key_value_table`<br>Costs one EXISTS query when nothing is suspended. |
| `src/django_app/plugins/services/presenter.py` | List/detail shape:<br>• `status` (`suspended` wins over `state`)<br>• `access[].resource_id/resource_name`, resolved by type + `manifest_ref`<br>• slots with `configured`<br>• `contents` counts<br>• `dev_mode_available`, `dev_ui_url`, `dev_ui_user`<br>• `resources[]` (detail only; `exists:false` for rows the org deleted) |
| `src/django_app/plugins/services/ui_service.py` | `open_session()`: suspended / no UI / not ready → 409. Otherwise returns either the dev URL or `/api/plugin-ui/<token>/<entry>` with `expires_in: 43200`. Its `access` holds alias, type, actions and `resource_id`.<br>`find_asset()`: re-checks everything on every request. |
| `src/django_app/plugins/services/ui_token.py` | `django.core.signing` token: salt `plugins.ui`, claims `{plugin, org, user}`, `MAX_AGE_SECONDS = 12 h`. |
| `src/django_app/plugins/services/dev_ui_service.py` | `require_enabled`, `validate_dev_ui_url`, `set_url` (sets `dev_ui_user` and replaces any earlier URL), `clear` (allowed with the flag off), `dev_url_for(plugin, user)`. |
| `src/django_app/plugins/services/knowledge_service.py` | There is no worker. Plugin state is computed from indexing status on read (`refresh_states`). Also `start_indexing` and `retry`. |
| `src/django_app/plugins/services/secret_slot_service.py` | Re-entering slot values: create a new secret, re-bind it the way the file does, move references. |

**HTTP surface**

| File | Role |
|---|---|
| `src/django_app/plugins/views.py` | `PluginViewSet`:<br>• `OrgScopedViewSetMixin` + `IsAuthenticated, DenyApiKeyAuth, HasOrgPermission` (JWT only)<br>• `rbac_resource_type = PLUGINS`, no pagination<br>• Actions by permission: `nav` (use) · `inspect`, `install` (create) · `suspend`, `resume`, `retry`, `secrets`, `dev-ui` POST/DELETE (update) · `delete-preview` (delete) · `ui-session` (use) |
| `src/django_app/plugins/serializers.py` | Request bodies only. The install `secrets` field is a JSON **string** (multipart). Responses come from `PluginPresenter`. |
| `src/django_app/plugins/urls.py` | `SimpleRouter` `plugins/` + `plugin-ui/<token>/<path:asset_path>`. Mounted under `api/` by `src/django_app/django_app/urls.py`. |
| `src/django_app/plugins/asset_views.py` | `plugin_ui_asset` is a plain Django view: no DRF, no JWT, no cookies.<br>• Fetch-Metadata refusal runs before the token is read.<br>• Headers: `CONTENT_SECURITY_POLICY` + `ASSET_HEADERS`.<br>• `@xframe_options_sameorigin` — Django's middleware would otherwise send DENY.<br>• Every failure is an empty 404. |

**Samples and tooling**

| File | Role |
|---|---|
| `src/django_app/plugins/management/commands/plugin_export_resources.py` | `--sample {chat-bot,chat-admin} --output <path>`: builds the sample's rows in a rolled-back transaction, exports them with `ExportService`, and prints the refs that `plugin.json` must use. |
| `src/django_app/plugins/samples/chat-bot/` | **Bridge v1** sample: plain JS `ui/` with a hand-written `bridge-client.js`, plus knowledge and a storage file. Used by most backend tests through `zip_builder`. |
| `src/django_app/plugins/samples/chat_admin_code/` | `append_turn.py`, `format_history.py`: source of the Chat Admin Python nodes, copied verbatim into `resources.json`. Standard library only, top-level `main`, no `from __future__`. |
| `src/django_app/plugins/samples/zip_builder.py` | `sample_files`, `build_zip`, `build_sample_zip(manifest_changes=…)` for tests. |

### Layer 2 — Django hooks outside the app

| File | Role |
|---|---|
| `src/django_app/django_app/settings/base.py` | `"plugins"` in `INSTALLED_APPS`; `PLUGINS_DEV_MODE = env.bool("PLUGINS_DEV_MODE", False)`. |
| `src/docker-compose.yaml`, `src/env.yaml`, `src/.env.example` | django_app env `PLUGINS_DEV_MODE: ${PLUGINS_DEV_MODE:?}`, which is **required**. Documented default `false`; `.env.example` has `False`. |
| `src/django_app/tables/services/session_manager_service.py` | `run_session()` calls `plugin_guard.check_flow(graph)` before the session row exists. Every trigger goes through here. |
| `src/django_app/tables/views/views.py` | The run-session view re-raises `PluginSuspendedError`, so its 409 envelope survives. Every other exception becomes 400 `{"error"}`. |
| `src/django_app/tables/services/converter_service.py` | Calls `check_tool` (MCP / Python tools) and `check_key_value_table` (in `convert_key_value_node_to_pydantic`). |
| `src/django_app/tables/services/base_node_payload_service.py` | Calls `check_agent_definition` for agent/task node payloads. |
| `src/django_app/rbac/models/enums.py`, `src/django_app/rbac/migrations/0004_plugins_resource_type.py` | `ResourceType.PLUGINS`. |
| `src/django_app/rbac/access/catalog.py` | `RESOURCE_TYPE_METADATA` entry with actions `create read update delete use`:<br>• create = install<br>• update = suspend / resume / secrets / dev-ui<br>• delete = uninstall<br>• use = open the page<br>Plus `RECOMMENDED_WITH["plugins"]`: create and delete recommend the same action on every bundled RBAC type. |
| `src/django_app/rbac/access/builtin_roles.json` | Only **Org Admin** gets `plugins` (all five actions). Member and Viewer get none. |
| `src/django_app/rbac/access/effective.py` | `use` is grantable only on `secrets` and `plugins`. |

### Layer 3 — import/export pieces plugins rely on

General machinery: `wiki/topics/import-export.md` (config repo) and `/new-import-export`. Only the plugin-relevant deltas are listed here.

| File | Role |
|---|---|
| `src/django_app/tables/import_export/enums.py` | `EntityType.KEY_VALUE_TABLE = "KeyValueTable"`. |
| `src/django_app/tables/import_export/constants.py` | `DEPENDENCY_ORDER`: `KEY_VALUE_TABLE` comes after `WEBHOOK_TRIGGER`, **before `GRAPH`**, so KV nodes can bind the imported table. |
| `src/django_app/tables/import_export/permissions.py` | `ENTITY_RESOURCE_MAP[KEY_VALUE_TABLE] = KEY_VALUE_TABLES`. |
| `src/django_app/tables/import_export/serializers/key_value_table.py` | `id, name, description` only. Entries are never exported. |
| `src/django_app/tables/import_export/strategies/key_value_table.py` | Strict org scope. `find_existing`: iexact name in the importing org (None without an org). `create_entity` uses a savepoint. On a name collision, a **forced** create raises; a plain import reuses the existing table. |
| `src/django_app/tables/import_export/strategies/graph.py` | A flow export's dependencies include the same-org tables its KV nodes use. The node strategy does not, so partial export (copy/paste) carries no tables. |
| `src/django_app/tables/import_export/strategies/nodes/key_value_node.py` | Passes `imported_table_id` (the IDMapper lookup of the exported table id) to `resolve_reference`. |
| `src/django_app/tables/services/key_value_table_service.py` | `resolve_reference(..., imported_table_id)`: the carried table (same org) wins, then id+name, then name. Always gated by `MODE_PERMISSIONS` (read→read, write→create+update, delete→read+delete). `delete_table` is used by plugin delete. |
| `src/django_app/tables/import_export/schemas.py` | `ImportSettings.force_create_types`. |
| `src/django_app/tables/import_export/strategies/base.py`, `src/django_app/tables/import_export/services/import_service.py` | A forced type skips `find_existing`. Creating it is still gated by `effective_permissions`. |
| `src/django_app/tables/apps.py` | Registers `KeyValueTableStrategy`. |
| `src/django_app/tables/views/model_view_sets.py` | `KeyValueTableEntryViewSet.KeyValueTableEntryFilter`:<br>• `table` (`NumberFilter`; a foreign id returns empty, not 400)<br>• `key` (exact, case-sensitive) — what `kv.get` uses |

### Layer 4 — frontend (`frontend/src/app/features/plugins/` + integration)

58 files, 16 specs. Owner: `angular-dev`.

| File | Role |
|---|---|
| `frontend/src/app/features/plugins/models/plugin.model.ts` | Every API shape:<br>• `PluginResourceType` union (mirrors the Python enum)<br>• `PluginAccessTargetType`, `PluginAccessAction`<br>• summary/detail, inspect, delete preview, `PluginNavItem`<br>• `PluginUiSession` (`dev_mode`, `expires_in: number \| null`)<br>• `PluginErrorCode` |
| `frontend/src/app/features/plugins/services/plugins-api.service.ts` | REST: list, `nav`, get, inspect, install (upload progress), suspend/resume/retry, secrets, delete-preview, delete, `ui-session`, `setDevUi`/`clearDevUi`. |
| `frontend/src/app/features/plugins/services/plugins-store.service.ts` | Signals: `plugins`, `navPlugins`. The nav refresh effect runs on org change and `plugins:use`. A generation counter drops stale-org responses. |
| `frontend/src/app/features/plugins/plugins.providers.ts` | `providePluginsStorages()` registers the store in `APP_STORAGE`, which is cleared on org switch and logout. |
| `frontend/src/app/features/plugins/components/plugins-section/` | Settings → Plugins tab: list, status, Add, Suspend/Resume, Secrets, Retry, Delete. "Dev mode" shows only when `dev_mode_available && has_ui` and the user has `plugins:update`. |
| `frontend/src/app/features/plugins/components/plugin-install-dialog/` | Upload (client cap `PLUGIN_MAX_FILE_MEGABYTES = 30`) → review (contents, access, warnings, conflicts, missing permissions) → slot values → install. |
| `frontend/src/app/features/plugins/components/plugin-secrets-dialog/`, `.../plugin-secret-destinations/` | Re-enter slot values; show where each value goes. |
| `frontend/src/app/features/plugins/components/plugin-dev-mode-dialog/` | Set or clear the dev URL. |
| `frontend/src/app/features/plugins/components/plugin-delete-dialog/` | Delete preview (resources, sessions, external usages, missing permissions) → delete. |
| `frontend/src/app/features/plugins/pages/plugin-host-page/plugin-page.matcher.ts` | `pluginPageMatcher` consumes `plugins/<id>/**` (posParam `id`) and **rejects matrix params**. |
| `frontend/src/app/features/plugins/pages/plugin-host-page/plugin-host-page.component.ts` (+ `.html`) | Provides **one `PluginBridgeHost` per page**. Flow: `ui-session` → validated frame URL (+ `#<path>` for v2) → `attach` → sets `src`. Copies `nav.changed` into the router and route changes into `nav.navigate`. Also the DEV banner and the message states. The iframe `sandbox`, `referrerpolicy` and `allow` attributes are written literally in the template. |
| `frontend/src/app/features/plugins/bridge/bridge-protocol.ts` | Message shapes (`ready`, `init`, `error`, `request`, `response`, `event`) and error codes.<br>• `BRIDGE_LIMITS`: 64 KB per request, 10 in flight, 4 subscriptions, 20 runs/min.<br>• `BRIDGE_V2_LIMITS`: 120 nav/min, path ≤ 1024, KV text ≤ 512, page size ≤ 100 (default 20).<br>• `supportsHostEvents(v)` = `v >= 2`. |
| `frontend/src/app/features/plugins/bridge/bridge-method.ts` | `BridgeMethodContext` (v1), `BridgeMethodContextV2` (+ nav), `BridgeMethodDefinition {paramKeys, resultKeys, invoke}`. |
| `frontend/src/app/features/plugins/bridge/bridge-tables.ts` | `BRIDGE_TABLES = {1: V1, 2: V2}` is the version registry. Lookup is own-property only. |
| `frontend/src/app/features/plugins/bridge/v1/bridge-v1.methods.ts` | **Frozen v1 public contract:** `bridge.hello`, `flows.run`, `sessions.get/subscribe/unsubscribe/stop`. |
| `frontend/src/app/features/plugins/bridge/v2/bridge-v2.methods.ts` | v2 = the v1 definitions, by reference, plus its own `bridge.hello`, `kv.list`, `kv.get` and `nav.changed`. |
| `frontend/src/app/features/plugins/bridge/access-policy.ts` | `ACCESS_TYPES_BY_VERSION`. `buildAccessPolicy(entries, version)` returns a `Map` and drops deleted, unknown-type and malformed entries. Also `resolveAlias`, `aliasForResource`, `assertAnyGrant`, `describeAccess` (no ids). |
| `frontend/src/app/features/plugins/bridge/plugin-bridge-host.service.ts` | `PluginBridgeHost`:<br>• handshake: `event.source` and `origin === "null"`<br>• per-request checks, rate windows, page-scoped sessions<br>• `notifyNavigation`, theme effect, stop on org switch<br>• production: a 2nd `load` tears the page down; dev: a 2nd `ready` resets the connection<br>• `toBridgeError` |
| `frontend/src/app/features/plugins/bridge/plugin-bridge-api.service.ts` | The bridge's only HTTP, made as the signed-in user, each call with `bridgeContext()` (`SKIP_FORBIDDEN_RELOAD`): run-session, session get/stop, KV list / find-by-key / get, SSE URL. |
| `frontend/src/app/features/plugins/bridge/plugin-session-stream.ts` | One SSE stream per subscription (`run-session/subscribe/<id>/?ticket=` via `SseTicketService`); 3 reconnects; 3 s grace after a terminal status. |
| `frontend/src/app/features/plugins/bridge/plugin-nav-path.util.ts` | Path grammar, `canonicalNavPath`, path ⇄ router segments + query. |
| `frontend/src/app/features/plugins/bridge/testing/bridge-test-harness.ts` | `FakeMessagePort` / `FakeMessageChannel` (synchronous delivery) for bridge specs. |
| `frontend/src/app/features/plugins/services/plugin-host-theme.service.ts` | `PLUGIN_THEME_TOKENS`: 22 `--es-*` names mapped from EpicStaff variables. Add, never rename. `LIGHT_THEME_CLASS = 'my-app-light'`; a MutationObserver drives the `theme` signal. |
| `frontend/src/app/features/plugins/utils/plugin-frame-url.util.ts` | `toPluginFrameUrl` (same-origin `/api/plugin-ui/` only), `toPluginDevFrameUrl` (mirrors the backend dev URL rule), `withPluginNavFragment`. |
| `frontend/src/app/features/plugins/utils/plugin-display.util.ts` | `PLUGIN_RESOURCE_TYPE_LABELS` is an exhaustive `Record`, so a missing type is a compile error. Also labels and `isPluginIconUrl`. |
| `frontend/src/app/features/plugins/utils/plugin-error.util.ts`, `.../plugin-secret-value.util.ts` | API error → view model; slot value validators (4096). |
| `frontend/src/app/app.routes.ts` | Route `{matcher: pluginPageMatcher, loadComponent: PluginHostPageComponent, canActivate: [permissionGuard], data: {permission: [Plugins, Use]}}`. |
| `frontend/src/app/app.config.ts` | `...providePluginsStorages()`. |
| `frontend/src/app/layouts/main-layout/sidenav/sidenav.component.ts` (+ `.html`) | **Where plugin icons enter the nav.** `topNavItems = [...static, ...pluginNavItems()]`, from `PluginsStoreService.navPlugins()`. Each item: route `/plugins/<id>`, `iconUrl` or the `diamond-grid` fallback, gated by `plugins:use`. `routerLinkActiveOptions {exact:false}` keeps the button active on deep links. |
| `frontend/src/app/features/configure-models/components/configure-models-dialog/configure-models-dialog.component.ts` (+ `.html`, `frontend/src/app/features/configure-models/enums/configure-models-tab-id.enum.ts`) | The Settings dialog. Tab `PLUGINS` renders `<app-plugins-section />`, gated by `plugins:read`. |
| `frontend/src/app/services/auth/permissions.service.ts` | `canOpenConfigureModelsDialog()` is also true for `plugins:read`. |
| `frontend/src/app/shared/models/role-based-access/permissions.model.ts` | `ResourceCode.Plugins`, `ActionCode.Use`. |
| `frontend/src/app/core/interceptors/forbidden.interceptor.ts`, `frontend/src/app/core/interceptors/skip-forbidden-reload.context.ts` | `BUSINESS_RULE_FORBIDDEN_CODES` includes `plugin_install_forbidden` and `plugin_delete_forbidden`. `SKIP_FORBIDDEN_RELOAD` is the context token the bridge sets. |

### Layer 5 — `plugin-sdk/` (author SDK + CLI)

TypeScript, ESM, outside `frontend/`. No frontend lint, no third-party notices, not in any Docker context, not in CI. Architecture view: [[plugin-author-tooling]].

| File | Role |
|---|---|
| `plugin-sdk/package.json` | `@epicstaff/plugin-sdk` (private). Exports `.`, `./storage-shim`, `./mock-host`. Bin `epicstaff-plugin`. Node ≥ 22.18. `npm test` = build + typecheck + `node --test`. |
| `plugin-sdk/src/protocol.ts` | The SDK's **copy** of the v2 protocol: `BRIDGE_VERSION = 2`, limits, access actions, `THEME_TOKENS`, nav grammar, KV rules, method param keys, session statuses. |
| `plugin-sdk/src/client.ts` | `connect(options)` → `EpicStaffBridge`, with `context`, `call`, `on`, `flows.run/runAndWait`, `sessions.*`, `kv.list/get`, `nav`, `theme`. Uses the mock host when `isFramed()` is false. |
| `plugin-sdk/src/connection.ts` | `BridgeConnection`: handshake, request ids, timeouts, release of abandoned requests. |
| `plugin-sdk/src/run-and-wait.ts` | `flows.run` → `sessions.subscribe` → resolves with `graph_end.end_node_result`. Rejects on `error`/`stop`/`expired`, on close without output, or on timeout (5 min default). |
| `plugin-sdk/src/nav-sync.ts`, `plugin-sdk/src/nav-path.ts` | Patches `pushState` → `replaceState` + `nav.changed`. Applies `nav.navigate` (replaceState + synthetic `popstate`/`hashchange`). `hashToNavPath`. |
| `plugin-sdk/src/theme.ts` | Applies `--es-*` to `<html>`, plus `data-es-theme` and `color-scheme`; follows `theme.changed`. |
| `plugin-sdk/src/storage-shim.ts`, `plugin-sdk/src/storage.ts` | Side-effect import: in-memory `localStorage`, `sessionStorage` and `document.cookie` wherever access throws (`force` option). |
| `plugin-sdk/src/mock-host.ts` | `createMockHost({access, flows, kvTables})` over a MessageChannel, for standalone development. |
| `plugin-sdk/src/errors.ts`, `plugin-sdk/src/report-error.ts`, `plugin-sdk/src/index.ts` | `BridgeCallError {code}`, `FlowRunError`; callback error reporting; public exports. |
| `plugin-sdk/bin/epicstaff-plugin.mjs` | `validate <dir> [--ui <build>]`, `pack <dir> [--ui <build>] --out <zip>`. Exit codes 0 / 1 / 2. |
| `plugin-sdk/cli/rules.mjs` | **Mirror** of the `manifest.py` + `bundle_reader.py` rules: versions, limits, types, patterns, `ALLOWED_RESOURCE_TYPES`, `ACCESS_TYPES`, `IMPORT_VERSION = 3`. The server stays authoritative. |
| `plugin-sdk/cli/validate.mjs`, `plugin-sdk/cli/html-lint.mjs`, `plugin-sdk/cli/bundle-files.mjs` | Validation; HTML lint (inline `<script>`, `on*=`, `<base>`, `javascript:`); folder walk. |
| `plugin-sdk/cli/pack.mjs`, `plugin-sdk/cli/zip.mjs` | Deterministic, dependency-free zip writer: deflate/store, no directory entries, fixed timestamp. |
| `plugin-sdk/README.md` | Author guide: sandbox rules table, framework build settings, dev mode. |

### Layer 6 — Chat Admin sample (`plugin-samples/chat-admin/`)

| File | Role |
|---|---|
| `plugin-samples/chat-admin/plugin/plugin.json` | `bridge: 2`, `id: chat-admin`, `ui.entry: ui/index.html`, `icon: ui/icon.svg`. Slot `OPENAI_API_KEY` is bound to `LLMConfig` ref 1 `api_key_secret`. Access: `chat` (flow 1: run, sessions.read, sessions.stop) and `conversations` (key_value_table 1: read). |
| `plugin-samples/chat-admin/plugin/resources.json` | Generated by `plugin_export_resources --sample chat-admin`: Flow, AgentDefinition, LLMConfig, LLMModel, KeyValueTable `conversations`. Import version 3. |
| `plugin-samples/chat-admin/app/package.json`, `plugin-samples/chat-admin/app/angular.json` | Angular 22.2.1; SDK via `file:../../../plugin-sdk`; scripts `build:sdk`, `build`, `validate`, `pack`.<br>• Production: `inlineCritical: false`, `fonts: false`, `outputHashing: all`.<br>• `polyfills` = the storage shim.<br>• Dev server: port 4300 + ACAO `*`. |
| `plugin-samples/chat-admin/app/src/main.ts`, `.../src/app/app.config.ts`, `.../src/app/app.routes.ts` | Shim imported first; zoneless; `withHashLocation()`; `connect()` in `provideAppInitializer`. Routes: `chat`, `chat/:id`, plus lazy `conversations`, `conversations/:key`, `about`. |
| `plugin-samples/chat-admin/app/src/app/core/plugin-bridge.service.ts` | The app's one connection; loads the mock host lazily. |
| `plugin-samples/chat-admin/app/src/app/conversations/conversations-api.service.ts` | `kv.list` / `kv.get` on `conversations`; `flows.runAndWait('chat', {conversation_id, question})`. |
| `plugin-samples/chat-admin/app/src/app/mock/chat-admin-mock-host.ts` | Mock data and a mock `chat` flow (lazy chunk, never loaded when framed). |
| `plugin-samples/chat-admin/README.md` | Build, pack and dev-mode steps. |

Sample flow: Start `{conversation_id, question}` → KV read "Load conversation" → Python "Format history" → Task "Answer" → Python "Append turn" → KV write "Save conversation" → End `{answer, conversation_id}`. The app sends only the id and the question.

### Tests

| Location | Covers |
|---|---|
| `src/django_app/tests/plugins_tests/` | 12 modules, 194 `test_` functions, plus `conftest.py` and `helpers.py`. Covers:<br>• install, KV tables, lifecycle, guard<br>• permissions (incl. cross-org 404, only Org Admin seeded)<br>• UI assets (exact CSP, ACAO, Fetch-Metadata, 12 h token, canonical paths)<br>• dev mode, nav, knowledge, secret destinations<br>• registry consistency (`test_plugin_resource_types.py`)<br>• the Chat Admin sample (`test_chat_admin_sample.py`) |
| `src/django_app/tests/import_export_tests/test_key_value_table_import_export.py`, `.../test_import_force_create.py` | KV entity export/import, IDMapper binding, never another org's table, perms, legacy by-name binding, `IMPORT_VERSION` unchanged; `force_create_types`. |
| `src/django_app/tests/services_tests/test_key_value_node_copy_import.py` | Partial export carries no table; binding gated by mode permissions. |
| `src/django_app/tests/api_tests/test_key_value_tables_api.py` | `?table=&key=` exact filter; foreign table → empty. |
| `src/crew/tests/clients/test_key_value_client.py` | Missing `DJANGO_API_KEY` → `ClientNotAvailableError`. |
| `frontend/src/app/features/plugins/**/*.spec.ts` | 16 specs. `bridge/v1/bridge-v1.contract.spec.ts` and `bridge/v2/bridge-v2.contract.spec.ts` pin the public contract. |
| `plugin-sdk/test/` | 9 `node --test` files: client, connection, runAndWait, nav sync, theme, storage shim, mock host, CLI validate, CLI pack. |

---

## Cross-layer contracts

### Contract 1 — package: `plugin.json` ↔ `resources.json` ↔ importer (`plugin-package-contract`)

Full spec: [[plugin-package-format]]. Every rule below is enforced in `src/django_app/plugins/manifest.py` unless noted. A violation is a 400 `invalid_plugin` listing every `{loc, message}`.

| Rule | Enforced by |
|---|---|
| `resources.json` is a **Flow** export (`main_entity: "Flow"`). Any import version the server converts (≤ 3). | `_load_resources` |
| Only `PLUGIN_OWNED_TYPES ∪ CATALOG_TYPES` entity lists. | `_check_resource_types` |
| Every `ref` is the `id` of an entity inside `resources.json`. The type depends on the field:<br>• `secret_bindings[].entity`<br>• `knowledge[].embedder` → EmbeddingConfig<br>• `attach_to_surfaces` / `storage_files[].surfaces[].surface` → Surface<br>• `attach_to_flows` → Flow<br>• `access[].ref` → `ACCESS_ENTITY_TYPES[type]` | `_check_refs` |
| Alias `^[a-z][a-z0-9_-]{0,63}$`, unique. Actions per type: flow = run, sessions.read, sessions.stop; key_value_table = read. `key_value_table` access needs `bridge ≥ 2`. | `AccessEntry`, `PluginManifest._consistent` |
| A secret slot `^[A-Z][A-Z0-9_]{0,59}$` becomes the org Secret `<PLUGIN_ID upper, - → _>__<SLOT>` (e.g. `CHAT_ADMIN__OPENAI_API_KEY`). It is bound by **FK** (`LLMConfig` / `EmbeddingConfig.api_key_secret`, `MCPTool.auth_secret`), never by name. Code calling `get_secret("X")` is rejected. | `slot_secret_name`, `SECRET_BINDING_FIELDS`, `_check_name_bound_secrets`; a taken name → 409 (`find_conflicts`) |
| A KV table is installed as `<plugin_id, - → _>__<name>` (e.g. `chat_admin__conversations`): ≤ 255 chars, unique iexact in the org. It is renamed **once**, at load, and the nodes' `key_value_table_name` is rewritten with it. | `key_value_table_name`, `_with_installed_table_names`; conflict → 409 |
| Every KV node naming a table must name a table the bundle ships. This closes by-name rebinding to the org's own tables. | `_check_key_value_nodes` |
| Owned types are force-created and only **created** rows are registered (`manifest_ref = str(resources.json id)`). Catalog rows are reused and never registered. The exception is an org-owned model the import had to create. | `install_service.py`, `resource_types.py` |
| Storage files are written to `plugins/<plugin_id>/<path under files/>`. | `PluginPackage.storage_path`; taken → 409 |

### Contract 2 — bridge versions are frozen (`bridge-version-freeze`)

Specs: [[plugin-bridge-v1]], [[plugin-bridge-v2]].

- **One version = one method table.**
  - v1 never changes: not a method name, param, result key, error code or the HTTP call behind it.
  - v2 reuses the v1 definitions by reference.
  - New behaviour means a new `bridge/vN/` table.
- **Must agree:**
  - backend `SUPPORTED_BRIDGE_VERSIONS` (`manifest.py`)
  - frontend `BRIDGE_TABLES` keys
  - CLI `SUPPORTED_BRIDGE_VERSIONS` (`cli/rules.mjs`)
  - frontend `ACCESS_TYPES_BY_VERSION` ⇔ backend `ACCESS_MIN_BRIDGE_VERSION`
  - The SDK speaks only `BRIDGE_VERSION = 2`.
- **Every message carries `v`.** If `ready.v` ≠ the plugin's `bridge_version`, the host answers `{kind:"error", error:{code:"unsupported"}}`.
- **Pinned by** `bridge-v1.contract.spec.ts`, `bridge-v2.contract.spec.ts` and backend `test_supported_versions`.
- **Failure mode:** an installed plugin breaks after an EpicStaff upgrade. Nothing on the server checks the frontend tables.

### Contract 3 — plugin page sandbox (`plugin-page-sandbox`)

| Part | Rule |
|---|---|
| iframe | `sandbox="allow-scripts"` and **never** `allow-same-origin`, so the origin is opaque (`"null"`). `referrerpolicy="no-referrer"`; `allow` denies camera, microphone and geolocation. `src` is set only after `attach`, and only from `toPluginFrameUrl` / `toPluginDevFrameUrl`. |
| Asset headers (`asset_views.py`) | Exact CSP:<br>`sandbox allow-scripts; default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; media-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'`<br>Plus `nosniff`, `no-store`, `Referrer-Policy: no-referrer`, `Cross-Origin-Resource-Policy: cross-origin`, **`Access-Control-Allow-Origin: *`** and X-Frame-Options SAMEORIGIN. No credentials are read or set. |
| Fetch Metadata | A `Sec-Fetch-Mode` of navigate/nested-navigate with `Sec-Fetch-Dest` ≠ `iframe` → 404. A `.html` / `.svg` request without `Sec-Fetch-Dest` → 404. Scripts, styles, fonts and images are unaffected. Runs before the token is read (0 queries). |
| Token | `signing.dumps({plugin, org, user}, salt="plugins.ui")`, valid 12 h, reusable for every file of the page. Every request re-checks:<br>• same org, not suspended, has UI, READY<br>• user active, member, `plugins:use`<br>• canonical path, allowed extension |
| Handshake | The host accepts `ready` only when `event.source` is the frame's window **and** `event.origin === "null"`. It posts `init` with target `'*'` (an opaque origin can't be named; the source check pins the target) and transfers `port2`. |

### Contract 4 — effective access (`plugin-effective-access`)

**Effective access = the logged-in user's RBAC ∩ the plugin's access list.**

- **The host narrows first, in the browser, before any HTTP:** `buildAccessPolicy` → `resolveAlias` / `assertAnyGrant`, page-scoped sessions (`isOwnSession`), and the caps.
- **The server then applies the user's own RBAC** to what is an ordinary API call. It cannot tell a bridge call from the user's own UI.
- **The page never sees a database id.**
  - `init` and `bridge.hello` list aliases only.
  - `kv.list` strips `id`, `table` and `updated_by_*`.
  - `kv.get` resolves the key itself, then re-checks that `table` and `key` match.
- **A deleted resource drops out.** The presenter returns `resource_id: null`, the grant is dropped, and calls get `forbidden`.
- **Required permissions:** opening the page, `ui-session` and `nav` need `plugins:use`. The Settings tab needs `plugins:read`.

### Contract 5 — deep links (`plugin-deep-link-path`)

- **Address:** `/plugins/<Plugin.pk>/<app path>[?query]`. It uses the **database id**, not the `plugin_id` slug. The matcher consumes the whole URL, and matrix params match nothing.
- **Path grammar:** ≤ 1024 chars, `^/(seg(/seg)*)?(\?query)?$`, no `.` / `..` segments, valid `%` escapes. It is identical in `plugin-nav-path.util.ts` and the SDK `protocol.ts`.
- **v2 opening:** the host puts the path in the frame URL fragment (`…/index.html#<path>`) and in `init.context.nav.path`.
- **v2 page → host:** `nav.changed {path, replace}` → `router.navigate(['/plugins', id, ...segments], {queryParams, replaceUrl})`.
- **v2 host → page:** a route change sends `nav.navigate`. The host's history is the only history; the SDK turns the page's `pushState` into `replaceState` + a report.
- **v1:** the path is ignored.
- **Conflicts:** a navigation the user started wins over a concurrent `nav.changed`. `nav.changed` is capped at 120/min.

### Contract 6 — dev mode guard (`plugin-dev-mode-guard`)

All of these must hold:

1. **Instance flag.** `settings.PLUGINS_DEV_MODE`. Compose requires it to be set. If off: `require_enabled` → 409 `plugin_dev_mode_disabled`, and `dev_mode_available: false`.
2. **Per user.** `dev_url_for` serves the dev URL only to `dev_ui_user`. Everyone else gets the installed files. There is one dev URL per plugin, and the last admin to set it owns it.
3. **Loopback only.** Plain `http` on `localhost` or `127.0.0.1`, optional port and path, no userinfo, query or fragment, ≤ 255 chars. Checked by the server (`DEV_UI_URL_PATTERN`) and the client (`toPluginDevFrameUrl`).
4. **`plugins:update`** with JWT for `POST/DELETE /api/plugins/{id}/dev-ui/`. DELETE works with the flag off.

How the host behaves differently in dev mode:
- It ignores later `load` events.
- A new `ready` resets the connection (rate windows carry over).
- It shows a DEV banner.

The dev page is served by the author's dev server, so the server CSP does not apply to it. Any page loaded in the frame gets the bridge with the developer's permissions.

### Contract 7 — key-value table export entity (`plugin-key-value-table-export`)

- **Format:** `"KeyValueTable": [{id, name, description}]`. The definition only, never entries.
- **Order and version:** `DEPENDENCY_ORDER` puts it before `GRAPH`. `IMPORT_VERSION` stays **3**; older servers ignore the key.
- **What travels:** a **full** flow export carries the same-org tables its KV nodes use. A partial export (copy/paste) never does.
- **KV node binding on import:** the IDMapper-mapped table (same org) first, then id+name, then name. Always gated by `MODE_PERMISSIONS`.
- **Consequence for plain imports:** they now create missing tables, which needs `key_value_tables:create`. Reusing a table with the same name does not.
- **Bridge dependency:** `GET /api/key-value-table-entries/?table=<id>&key=<exact>` (exact, case-sensitive), on the existing org-scoped viewset (`table__org_id`).

### Contract 8 — SDK and CLI mirror host and server (`sdk-host-protocol-mirror`)

These are copies, not shared code. Nothing checks them against the source of truth, and `.github/workflows/` runs neither `plugin-sdk/` tests nor the sample build.

| Copy | Source of truth | At `bfeea626f` |
|---|---|---|
| `plugin-sdk/src/protocol.ts` `THEME_TOKENS` | `PLUGIN_THEME_TOKENS` in `plugin-host-theme.service.ts` | identical (22 tokens) |
| `plugin-sdk/src/protocol.ts` `NAV_PATH_PATTERN` | `plugin-nav-path.util.ts` | identical |
| `plugin-sdk/src/protocol.ts` `BRIDGE_LIMITS` | `BRIDGE_LIMITS` + `BRIDGE_V2_LIMITS` | spot-checked: 64 KB, 10, 4, 20, 120 |
| `plugin-sdk/cli/rules.mjs` | `manifest.py`, `bundle_reader.py` | versions and size caps spot-checked |
| `toPluginDevFrameUrl` | `DEV_UI_URL_PATTERN` | same rule (the client uses `\d`, the server `[0-9]` plus a range check) |

---

## Data flow at runtime

```
INSTALL
Settings → Plugins → Add plugin            (plugin-install-dialog, client cap 30 MB)
  POST /api/plugins/inspect/   multipart file                       [plugins:create, JWT only]
    read_bundle → load_package → reject_if_installed
    → missing_permissions + find_conflicts → build_preview          writes nothing
  POST /api/plugins/install/   file + secrets (JSON string)
    same checks → 403 plugin_install_forbidden / 409 plugin_resource_conflict before any write
    _PluginInstallation.run()   one transaction
      Plugin → Secret <SLUG>__<SLOT> per slot
      → ImportService.import_data(resources, GRAPH, force_create_types=PLUGIN_OWNED_TYPES)
           … KeyValueTable (before GRAPH) → Graph → KeyValueNode binds via IDMapper
      → PluginResource per created row → secret FK bindings → knowledge → storage files → PluginAsset
      on_commit: knowledge_service.start_indexing   (PREPARING until indexed; recomputed on read)

OPEN THE PAGE
sidenav ← PluginsStoreService.navPlugins ← GET /api/plugins/nav/   (READY, not suspended, has UI)
/plugins/<id>[/<app path>] → pluginPageMatcher → PluginHostPageComponent   [permissionGuard plugins:use]
  POST /api/plugins/<id>/ui-session/ → PluginUiService.open_session
     → {url: "/api/plugin-ui/<token>/index.html" | dev URL, expires_in, dev_mode,
        bridge_version, plugin, access:[{alias, type, actions, resource_id}]}
  toPluginFrameUrl | toPluginDevFrameUrl → (v2) withPluginNavFragment(url, "/<app path>")
  PluginBridgeHost.attach(frame, session, {initialPath, devMode, onNavChanged}) → frame.src = url
  GET /api/plugin-ui/<token>/<file>      (frame origin "null", no cookies, no JWT)
     plugin_ui_asset: Fetch-Metadata gate → find_asset (all re-checks) → bytes + headers | empty 404
  page (SDK connect): parent.postMessage({v, kind:"ready"}, "*")
  host: source === frame && origin === "null" && v === bridge_version
     → MessageChannel → {v, kind:"init", context:{plugin, access, nav?, theme?}} + port2

ONE BRIDGE CALL
page → port {v, kind:"request", id, method, params}
host: v · size ≤ 64 KB · in-flight ≤ 10 · method ∈ BRIDGE_TABLES[v] · paramKeys · alias+action · rate
  → PluginBridgeApiService (signed-in user's JWT, SKIP_FORBIDDEN_RELOAD)
     flows.run          POST /api/run-session/ → run_session → plugin_guard.check_flow → crew
     sessions.subscribe SSE /api/run-session/subscribe/<id>/?ticket=… → {kind:"event", topic:"session.*"}
     kv.list / kv.get   GET /api/key-value-table-entries/?table=<id>[&key=<k>&limit=1] → ids stripped
     nav.changed        router.navigate(['/plugins', id, ...segments], {replaceUrl})   (no HTTP)
host → port {v, kind:"response", id, result | error}; v2 host events nav.navigate, theme.changed
  (subscription: null)

SUSPEND / DELETE
POST /api/plugins/<id>/suspend/ → suspended=True → on_commit: stop live sessions of its flows
  then: nav hides it · ui-session 409 · assets 404 · a run touching its flow (or a subflow), agent,
  tool or KV table → PluginSuspendedError at session build
DELETE /api/plugins/<id>/ → delete permission on every row type → suspend → walk DELETE_ORDER
  → plugin row (cascades PluginResource, PluginAsset) → storage objects removed after commit
```

---

## Adding the next family member

**A bundled resource type** (a row a plugin installs):

1. Make sure the export entity exists and is registered (`/new-import-export`).
2. Add a `PluginResourceType` value and run `make -C <SRC> django-makemigrations ARGS="plugins"` for the choices. Add its `RESOURCE_MODELS` entry. A test requires the two key sets to be equal.
3. Add it to `IMPORTED_ENTITIES` (owned) or `CREATED_CATALOG_ENTITIES` / `CATALOG_TYPES`. `RBAC_RESOURCE_TYPES` derives the permission gate from this.
4. Add it to `RECOMMENDED_WITH["plugins"]` create and delete in `rbac/access/catalog.py` (test-enforced).
5. Add it to `DELETE_ORDER`, plus a branch in `delete()` if the row needs a service-level delete. Add its `EXTERNAL_USAGES`. **Neither is checked for completeness.**
6. If rows of this type run, add a guard method and its call site.
7. Frontend: the `PluginResourceType` union and `PLUGIN_RESOURCE_TYPE_LABELS` (compile-enforced).
8. CLI: `ALLOWED_RESOURCE_TYPES` in `cli/rules.mjs`.

**An access type** (something a page may use):

1. Backend: the `AccessType` / `AccessAction` literals, plus `ACCESS_ACTIONS_BY_TYPE`, `ACCESS_ENTITY_TYPES`, `ACCESS_MIN_BRIDGE_VERSION` and `ACCESS_RESOURCE_TYPES`. A test makes these agree.
2. Frontend: `PluginAccessTargetType` / `PluginAccessAction`, `TYPE_LABELS`, and `ACCESS_TYPES_BY_VERSION[<new version>]`. Never edit an existing version's entry.
3. Methods go in a **new** bridge table.
4. SDK `protocol.ts` and CLI `ACCESS_TYPES`.

**A bridge version:**

1. `bridge/vN/bridge-vN.methods.ts` (reuse earlier definitions by reference) and `bridge-vN.contract.spec.ts`.
2. `BRIDGE_TABLES[N]` and `ACCESS_TYPES_BY_VERSION[N]`. Check `supportsHostEvents`.
3. Backend `SUPPORTED_BRIDGE_VERSIONS`, and update `test_supported_versions`.
4. CLI `SUPPORTED_BRIDGE_VERSIONS`, SDK `BRIDGE_VERSION` and protocol.
5. A `plugin-bridge-vN` doc in `docs/proto/plugins/`.

---

## Conventions that apply

- **Backend:** `docs/backend-conventions.md`.
  - `PluginViewSet` uses `OrgScopedViewSetMixin` (`Plugin` is an `OrgScopedModel`). Cross-org access → 404, which the permission tests cover.
  - Every new `@action` needs an `rbac_action_map` entry → `/rbac-coverage`.
  - Tests run only through `make -C <SRC> django-tests` (`/choosing-django-tests`).
- **Frontend:** `docs/frontend-conventions.md`. The feature lives in `features/plugins/`. The only touches outside it are the sidenav, the Settings dialog tab, routes, providers, `permissions.service.ts` and the forbidden interceptor.
- **Repo:** `CLAUDE.md`. No ticket ids in code, and git actions need the developer's explicit yes.
- **Conventions specific to this feature:**
  - **Registries.** Each one is a dict, and a test asserts that related key sets agree (`test_plugin_resource_types.py`). Add a new member to every table in the same change.
  - **Stored values are never renamed:** `PluginResourceType` values and the `--es-*` theme tokens (add, never rename).
  - **Errors.** Every API error is a `CustomAPIExeption` subclass with a stable `default_code`; the frontend `PluginErrorCode` mirrors them.
  - **Response shapes** come from `PluginPresenter`. DRF serializers here are request-only.
  - **Bridge code:**
    - anything keyed by page input (alias, method) uses a `Map` or own-property lookup
    - every method declares `paramKeys` / `resultKeys`; unknown params → `bad_request` before `invoke`
    - errors go through `toBridgeError`; server error bodies never reach the page
    - every bridge HTTP call uses `bridgeContext()`
  - **Public contracts.** `bridge-v1.methods.ts` and `bridge-v2.methods.ts` carry a "PUBLIC CONTRACT" header, and the contract specs are the gate.

---

## Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `docker compose up` refuses to start because `PLUGINS_DEV_MODE` is missing | Compose declares `PLUGINS_DEV_MODE: ${PLUGINS_DEV_MODE:?}`. A `src/.env` created before this branch doesn't have it. | Add `PLUGINS_DEV_MODE=False`. Use `True` only on a local dev stack. |
| Every Key-Value node fails with "DJANGO_API_KEY is not configured; Key-Value nodes can't reach Django.", so Chat Admin can't load or save conversations | `src/.env.example` ships `DJANGO_API_KEY=none`. `src/shared/envtools.py` reads `"none"` as `None`, and `KeyValueClient._post` then refuses. | Set any random value (django_app seeds it as the system key at start), then recreate `django_app`, `crew` and `realtime`. |
| Angular CLI refuses to build or serve the sample on Node 24.3 | Angular CLI 22 needs Node `^22.22.3 \|\| ^24.15.0 \|\| >=26` (`app/package.json` engines). | Upgrade Node. Local-only workaround: `node node_modules/@angular/cli/bin/bootstrap.js build` (or `serve`). |
| Path routing breaks inside the frame, or Back needs two presses | An opaque-origin page may change only its URL's query and fragment. Assigning `location.hash` directly or using plain `#` links adds frame history entries. | Use a hash router built on `pushState` (`withHashLocation()`) and call `connect()` before the first navigation, so nav sync is active. |
| The app renders unstyled | Angular's default `inlineCritical: true` loads CSS through an inline `onload` handler, which the CSP blocks. | Set `optimization.styles.inlineCritical: false`. Also set `fonts: false` and bundle fonts with `@fontsource/*`. |
| Module scripts, lazy chunks or fonts fail with CORS errors | The frame's origin is `null`, and module scripts and fonts load in CORS mode. | Keep ACAO `*` in `ASSET_HEADERS`. A dev server needs `headers: {"Access-Control-Allow-Origin": "*"}`. |
| `localStorage`, `sessionStorage` or `document.cookie` throws at startup | The sandboxed origin is opaque. | Import `@epicstaff/plugin-sdk/storage-shim` first in `main.ts` **and** list it in `polyfills`, because shared lazy chunks run before main. |
| `fetch('/api/…')` from the page fails, and a `<base href>` has no effect | CSP `connect-src 'none'` and `base-uri 'none'`. | Go through the bridge. Remove `<base>` (`epicstaff-plugin validate` warns about it). |
| Opening `/api/plugin-ui/<token>/index.html` in a tab returns 404 | Deliberate Fetch-Metadata refusal of top-level documents: otherwise a leaked link acts as a 12 h page on EpicStaff's domain. `.html` and `.svg` also need `Sec-Fetch-Dest`. | Open the page via `/plugins/<id>`. Plain `curl` of `.js` / `.css` still works for debugging. |
| A lazy screen fails to load after the page has been open for ~12 h | The token lives `MAX_AGE_SECONDS` = 12 h and every chunk needs it. | Reload, which issues a new `ui-session`. |
| The page is replaced by "The page tried to open another address, so EpicStaff closed it." | In production, a second iframe `load` counts as a navigation and the host tears the page down. This is cleanup, not a security boundary. | Don't navigate the frame. Dev mode ignores reloads. |
| A bridge call returns `forbidden` even though the alias is in `plugin.json` | One of: the user lacks the RBAC permission (API 403 → `forbidden`); the resource was deleted (`resource_id: null`); the action doesn't fit the type; or the type isn't served at the plugin's bridge version. | Walk Contract 4. |
| A bridge 403 remounts the whole EpicStaff page | A new bridge HTTP call is missing `bridgeContext()` (`SKIP_FORBIDDEN_RELOAD`), so `forbiddenInterceptor` treats the 403 as stale permissions. New plugin 403 codes have the same effect if missing from `BUSINESS_RULE_FORBIDDEN_CODES`. | Use `bridgeContext()`, and add business-rule 403 codes to that set. |
| `flows.run` returns `bad_request` for a large payload | Requests are capped at 64 KB. | Send ids and let the flow read state. Chat Admin reads the transcript from KV. |
| `kv.get` returns `bad_request` | The key must match `^[A-Za-z_][A-Za-z0-9_]*$` and be ≤ 512 chars (the KV tables' own rule). | Generate keys like `c_<24 hex>`. |
| A Member or Viewer sees no plugin icon and no Plugins tab | Among built-in roles, only Org Admin has `plugins`. | Use a custom role: `plugins:use` for the page, `plugins:read` for the tab. |
| No icon appears right after install | `nav` lists only plugins that are READY, not suspended and have a UI. Knowledge keeps a plugin PREPARING. | Wait for indexing; use Retry if the state is needs_attention. |
| Install fails with 403 `plugin_install_forbidden` listing `key_value_tables` update | A bundled KV node in write mode needs create + update (`MODE_PERMISSIONS`). Install refuses up front rather than importing a node with no table that fails on every run. | Grant the permissions. |
| Install fails with 409 `plugin_resource_conflict`, type `key_value_table` | The org already has `<slug>__<name>` (case-insensitive). Plugins never reuse org tables. | Rename or delete the org's table. |
| Install fails with 400 "A Key-Value node may only use a key-value table the plugin ships" | A KV node names a table that is not in `resources.json`; by-name rebinding would hand an org table to the plugin. | Export the full flow so its table travels with it. |
| Install fails with 409 `plugin_already_installed` for a newer version | The prototype has no in-place upgrade (`reject_if_installed`). | Delete the plugin, then install again. |
| A plain, non-plugin flow import now fails with 403 | The export now carries `KeyValueTable`, and creating a missing table needs `key_value_tables:create`. | Grant it, or create the same-name table first. |
| An org's own flow fails to start with `plugin_suspended` | It embeds a suspended plugin's flow as a subflow, or uses that plugin's agent, tool or KV table. | Resume the plugin, or unlink the resource. |
| Edits to `chat_admin_code/*.py` have no effect, or the test "resources.json is stale" fails | The node code is embedded in `resources.json`. | Re-run `plugin_export_resources --sample chat-admin`. If the printed refs changed, copy them into `plugin.json` (`test_the_committed_sample_installs` checks this). |
| A sample Python node raises SyntaxError in the sandbox | The sandbox puts the file inside a `try:` block (`src/sandbox/dynamic_venv_executor_chain.py`), so `from __future__` can't come first. | Standard library only, top-level `main`, no `__future__` imports. |
| The Dev mode button is missing, or `POST dev-ui` returns 400 `invalid` | The flag is off (`dev_mode_available: false`), the plugin has no UI, or the caller lacks `plugins:update`. For the 400: the URL is not plain `http` on `localhost` / `127.0.0.1`, or has userinfo, a query or a fragment. | Turn the flag on (local stacks only) and use e.g. `http://localhost:4300/`. |
| The plugin page never switches to light theme | Nothing in EpicStaff applies `.my-app-light`. It exists only in `frontend/src/styles/_variables.scss`. | Test from devtools. Known gap. |
| A suspended plugin's table is still editable from the Key-Value Tables page | The guard runs only at session build; `KeyValueTableEntryViewSet` has no guard. | Known, accepted gap. |
| After deleting a plugin, org rows of a newly added type are left behind | `deletable_rows()` walks only `DELETE_ORDER`, and nothing tests that it covers every type. | Add the type to `DELETE_ORDER` (see "Adding the next family member"). |
| After a data migration, suspend and delete no longer reach the plugin's rows | `PluginResource.object_id` is a bare primary key (`resource_types.py` NOTE). | Any migration that recreates rows under new pks must rewrite `PluginResource` in the same migration. |

---

## Related docs, skills and agents

**Sibling docs (`docs/proto/plugins/`):**
- [[plugins-prd]], [[plugins-rules]], [[plugins-architecture]] (C4 diagrams, decisions)
- [[plugin-package-format]], [[plugin-bridge-v1]], [[plugin-bridge-v2]], [[plugins-api-contract]], [[plugins-glossary]]
- [[plugin-author-tooling]] (SDK, CLI, dev mode; C4 view of the plugin side)
- [[alignment-plugin-apps]], [[plugin-apps-plan]], [[plugin-apps-status]]

**Wiki (config repo):** `wiki/topics/import-export.md`, `wiki/topics/auth-and-rbac.md`, `wiki/topics/nodes.md` (key-value node), `wiki/topics/files-storage.md`, `wiki/topics/knowledge-sources.md`.

**Skills:** `/new-import-export`, `/rbac-coverage`, `/choosing-django-tests`, `/proto-page`.

**Agents:**
- `architect` — cross-layer changes
- `backend-dev` — Django
- `angular-dev` — `features/plugins/`, and as the closest fit for the SDK and sample
- `backend-code-reviewer`, `frontend-code-reviewer`
- `security-reviewer` — always last for this feature

---

## Open questions / TODOs

- **Gap: `DELETE_ORDER` and `EXTERNAL_USAGES` are not checked for completeness** against `PluginResourceType`. One parametrised test would close a silent orphaning path.
- **Gap: the SDK and CLI copies (Contract 8) are not checked against their sources,** and no CI workflow runs `plugin-sdk` tests or builds the sample. Observed drift: the CLI ignores `Thumbs.db`, the server does not. This is harmless for CLI-packed zips, but a hand-made zip containing one is rejected.
- **Gap: no specialist owns `plugin-sdk/` or `plugin-samples/`.**
- **Open: secrets inside plugin apps.** Nothing is built.
- **Open: the access list is enforced only in the browser host.** That is by design while the sandbox holds, but it means the server can't audit or rate-limit plugin traffic separately from the user's own.
- **Known gaps** (from [[plugin-apps-status]]; not re-verified in the UI):
  - The delete preview shows a generic KV label and no row count.
  - A fresh org's install creates its own `gpt-4o-mini` `LLMModel`, which delete then removes.
  - The SDK mock host ships as a lazy chunk.
- **Open: Chrome Local Network Access** may block a localhost dev iframe when EpicStaff isn't served from localhost (risk 3 in [[plugin-apps-plan]]; unverified).
- **Decisions to revisit:** the route uses the database id rather than the slug; one dev URL per plugin; no in-place upgrade.

---

## Maintenance

This page is pinned to `proto/plugins-06-10-26 @ bfeea626f` and is not part of `wiki/`. Re-map it with `architect` after any commit that:

- adds or renames a `PluginResourceType`, an access type, or a bridge version
- touches `manifest.py`, `resource_types.py`, `install_service.py`, `lifecycle_service.py`, `guard.py`, `asset_views.py`, `ui_service.py`, `ui_token.py` or `dev_ui_service.py`
- changes `BRIDGE_TABLES`, `access-policy.ts`, `plugin-bridge-host.service.ts`, the host page, or `pluginPageMatcher`
- changes the KV export entity, `DEPENDENCY_ORDER`, `resolve_reference`, or the KV entries filter
- changes `plugin-sdk/src/protocol.ts`, `plugin-sdk/cli/rules.mjs`, or the Chat Admin sample's `plugin.json` / `resources.json`
- moves the plugin paths onto `developer`. At that point, move this page into `wiki/topics/plugins.md` and re-pin it.
