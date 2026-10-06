# Plugins API contract (prototype, frozen)

Status: **frozen**. The frontend builds against this document while the backend
finishes the lifecycle endpoints. A backend change that breaks a shape below must
update this file first and say so to the frontend.

**Changes since the first freeze** (all additive, no existing field changed):
1. New endpoint `GET /api/plugins/nav/` (USE), see "GET `/api/plugins/nav/`".
2. Two new resource type keys: `llm_model`, `embedding_model` (see "Resource type keys").
3. `POST /api/run-session/` refuses a suspended plugin's flow with 409 `plugin_suspended`
   (see "Suspended plugins and other endpoints").
4. `secret_slots[].destinations` on the inspect preview and on the Plugin object (list and
   detail): where each slot's value will be sent (see "Secret slot destinations").
5. The inspect `warnings` UI text is reworded (see "POST `/api/plugins/inspect/`").
6. Uninstall needs delete on every resource type it removes: `DELETE /api/plugins/{id}/`
   can answer 403 `plugin_delete_forbidden`, and delete-preview gains
   `missing_permissions` (see "DELETE `/api/plugins/{id}/`").

| Endpoint | Verb | RBAC (`plugins:`) | Implemented |
|---|---|---|---|
| `/api/plugins/` | GET | read | yes |
| `/api/plugins/nav/` | GET | **use** | yes |
| `/api/plugins/{id}/` | GET | read | yes |
| `/api/plugins/inspect/` | POST (multipart) | create | yes |
| `/api/plugins/install/` | POST (multipart) | create | yes |
| `/api/plugins/{id}/suspend/` | POST | update | yes |
| `/api/plugins/{id}/resume/` | POST | update | yes |
| `/api/plugins/{id}/retry/` | POST | update | yes |
| `/api/plugins/{id}/secrets/` | POST (JSON) | update (+ `secrets:create`) | yes |
| `/api/plugins/{id}/delete-preview/` | GET | delete | yes |
| `/api/plugins/{id}/` | DELETE | delete (+ delete on every contained type) | yes |
| `/api/plugins/{id}/ui-session/` | POST | use | yes |
| `/api/plugin-ui/{token}/{path}` | GET | (token) | yes |

## Common rules

- Every `/api/plugins/...` call needs `Authorization: Bearer <jwt>` and
  `X-Organization-Id: <org id>`. **API keys are refused** (403) on these routes.
- `{id}` is the plugin's database id (`id` below), never the manifest `plugin_id`.
- A plugin of another organization answers **404**, never 403.
- Built-in roles: **Org Admin** holds create/read/update/delete/use on `plugins`.
  Member and Viewer hold nothing, so for them every route above answers 403.
- Timestamps are ISO 8601 UTC strings (`"2026-10-06T21:30:00.123456Z"`).

### Error envelope

Every error uses the project envelope. `errors` is present only where listed.

```json
{
  "status_code": 400,
  "code": "invalid_plugin",
  "message": "The plugin file is invalid: 3 problems found.",
  "errors": [
    {"loc": "plugin.json.secret_slots.0.value", "message": "Extra inputs are not permitted"}
  ]
}
```

| HTTP | `code` | When | `errors` items |
|---|---|---|---|
| 400 | `invalid_plugin` | The file breaks the plugin format (see "What the server rejects") | `{"loc": str, "message": str}` — every problem found, not only the first |
| 400 | `invalid_plugin_secrets` | `secrets` misses a slot, names an unknown slot, or has a blank / over-4096-character value | `{"slot": str, "message": str}` |
| 400 | `invalid` | A request field is missing or malformed (no `file`, `secrets` not a JSON object) | — (`message` names the field) |
| 403 | `permission_denied` | The caller lacks the route's `plugins:` permission | — |
| 403 | `plugin_install_forbidden` | Install: the caller lacks create on a type the plugin bundles | `{"resource_type": str, "action": "create"}` |
| 403 | `plugin_delete_forbidden` | Delete: the caller lacks delete on a type the uninstall would remove | `{"resource_type": str, "action": "delete"}` |
| 403 | `org_membership_required` / 400 `org_context_required` | Bad or missing `X-Organization-Id` (shared RBAC errors) | — |
| 404 | `not_found` | Unknown id, or a plugin of another organization | — |
| 409 | `plugin_already_installed` | A plugin with this `plugin_id` is already installed in the org | `{"plugin_id": str, "installed_version": str}` |
| 409 | `plugin_resource_conflict` | A secret name or storage path the install would create is taken | `{"type": "secret" \| "storage_file", "name": str, "message": str}` |
| 409 | `plugin_suspended` | ui-session / retry on a suspended plugin; `POST /api/run-session/` for a suspended plugin's flow | — |
| 409 | `plugin_not_ready` | ui-session while status is `preparing` or `needs_attention` | — |
| 409 | `plugin_has_no_ui` | ui-session for a plugin without a page | — |
| 409 | `plugin_not_retryable` | retry while status is not `needs_attention` | — |

`message` is always human-readable and safe to show as-is.

## The Plugin object

Returned by list (`PluginSummary`), and by retrieve, install, suspend, resume,
retry and secrets (`PluginDetail` = `PluginSummary` + `resources`).

```json
{
  "id": 7,
  "plugin_id": "chat-bot",
  "version": "0.1.0",
  "name": "Chat Bot",
  "description": "A ready-made support assistant that answers questions about Acme Notes from its own knowledge base.",
  "icon_data_url": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0...",
  "format_version": 1,
  "bridge_version": 1,
  "has_ui": true,
  "status": "preparing",
  "state": "preparing",
  "status_reason": "",
  "suspended": false,
  "suspended_at": null,
  "access": [
    {
      "alias": "chat",
      "type": "flow",
      "actions": ["run", "sessions.read", "sessions.stop"],
      "resource_id": 42,
      "resource_name": "Chat Bot"
    }
  ],
  "secret_slots": [
    {
      "name": "OPENAI_API_KEY",
      "description": "OpenAI API key used by the chat model and by the knowledge embeddings.",
      "secret_id": 17,
      "secret_name": "CHAT_BOT__OPENAI_API_KEY",
      "configured": true,
      "destinations": [
        {"resource_type": "llm_config", "name": "Chat Bot GPT-4o mini", "provider": "openai", "host": null},
        {"resource_type": "embedding_config", "name": "Chat Bot embeddings", "provider": "openai", "host": null}
      ]
    }
  ],
  "contents": {
    "flow": 1,
    "agent_definition": 1,
    "surface": 1,
    "llm_config": 1,
    "embedding_config": 1,
    "secret": 1,
    "source_collection": 1,
    "storage_file": 1
  },
  "created_by": 3,
  "created_at": "2026-10-06T21:30:00.123456Z",
  "updated_at": "2026-10-06T21:30:00.123456Z",
  "resources": [
    {"type": "flow", "resource_id": 42, "name": "Chat Bot", "manifest_ref": "1", "exists": true},
    {"type": "secret", "resource_id": 17, "name": "CHAT_BOT__OPENAI_API_KEY", "manifest_ref": "OPENAI_API_KEY", "exists": true}
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | int | Use in every `{id}` URL. |
| `plugin_id` | string | Stable manifest id (`^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$`). Unique per org. |
| `icon_data_url` | string | `data:image/svg+xml;base64,...` or `data:image/png;base64,...`, or `""`. Render only with `<img [src]>`. |
| `has_ui` | bool | False means no nav button and no ui-session. |
| `status` | enum | **Drive the UI from this.** `"suspended"` when suspended, otherwise `state`. One of `preparing`, `ready`, `needs_attention`, `suspended`. |
| `state` | enum | `preparing` \| `ready` \| `needs_attention`, independent of suspension. |
| `status_reason` | string | Why the plugin needs attention; `""` otherwise. |
| `access[].resource_id` / `resource_name` | int / string, or null | `null` when the org deleted that flow. |
| `secret_slots[].configured` | bool | False when the slot's secret was deleted; the user can re-enter it via `secrets`. `secret_id` / `secret_name` are then `null`. |
| `secret_slots[].destinations` | array | Where a value entered for this slot now would be sent. On list and detail alike. See "Secret slot destinations". |
| `contents` | object | Count of installed rows per resource type (keys below); a type with none is absent. |
| `resources` | array | Detail responses only. `exists: false` (and `name: null`) for a row the org has since deleted. `manifest_ref` is where the row came from in the plugin file: a `resources.json` id, a slot name, a knowledge collection name or a `files/...` path. |

Resource type keys (`contents`, `resources[].type`, preview `contents[].type`):
`flow`, `agent_definition`, `surface`, `llm_config`, `embedding_config`,
`python_code_tool`, `mcp_tool`, `webhook_trigger`, `secret`, `source_collection`,
`storage_file`, `llm_model`, `embedding_model`.

`llm_model` / `embedding_model` (added after the first freeze) appear only after
install, never in inspect: they are the custom models the importer had to create
because the organization's model catalog had no match for a bundled config. A
catalog model the install reused is shared and never listed. Show them with a
generic label ("LLM model", "Embedding model").

## GET `/api/plugins/`

Response 200: a **plain JSON array** (not paginated) of `PluginSummary`, ordered by
name. No `resources` key.

## GET `/api/plugins/nav/`

The navigation buttons. Needs only `plugins:use`, so a role that may open plugin
pages but not see the Settings tab still gets its buttons. Reveals nothing else:
no access list, contents, slots, status or manifest.

Response 200: a **plain JSON array**, ordered by name, of the plugins of the active
organization whose page can open now: `status` is `ready` (so not suspended, not
preparing, not needing attention) and the plugin has a page.

```json
[
  {"id": 7, "name": "Chat Bot", "icon_data_url": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0..."},
  {"id": 9, "name": "Notes", "icon_data_url": null}
]
```

| Field | Notes |
|---|---|
| `id` | The plugin's database id: use it for `/plugins/:id` and `ui-session`. |
| `icon_data_url` | Same format as on the Plugin object, or **`null`** when the plugin has no icon (the Plugin object uses `""`). Render only with `<img [src]>`. |

Errors: 403 without `plugins:use` (a read-only role gets 403 here).

## GET `/api/plugins/{id}/`

Response 200: `PluginDetail`.

## POST `/api/plugins/inspect/`

Validates a plugin file and returns the review step's data. **Writes nothing.**

Request: `multipart/form-data`

| Field | Required | Notes |
|---|---|---|
| `file` | yes | The plugin `.zip`, at most 20 MB. |

Response 200:

```json
{
  "plugin": {
    "plugin_id": "chat-bot",
    "version": "0.1.0",
    "name": "Chat Bot",
    "description": "A ready-made support assistant ...",
    "icon_data_url": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0...",
    "format_version": 1,
    "bridge_version": 1,
    "has_ui": true
  },
  "contents": [
    {"type": "flow", "ref": "1", "name": "Chat Bot"},
    {"type": "agent_definition", "ref": "1", "name": "Chat Bot Agent"},
    {"type": "surface", "ref": "1", "name": "Chat Bot Agent knowledge"},
    {"type": "llm_config", "ref": "1", "name": "Chat Bot GPT-4o mini"},
    {"type": "embedding_config", "ref": "1", "name": "Chat Bot embeddings"},
    {"type": "secret", "ref": "OPENAI_API_KEY", "name": "CHAT_BOT__OPENAI_API_KEY"},
    {"type": "source_collection", "ref": "Acme Notes knowledge", "name": "Acme Notes knowledge", "documents": ["product-overview.md", "faq.md"]},
    {"type": "storage_file", "ref": "files/tone-guide.md", "name": "plugins/chat-bot/tone-guide.md"}
  ],
  "content_counts": {"flow": 1, "agent_definition": 1, "surface": 1, "llm_config": 1, "embedding_config": 1, "secret": 1, "source_collection": 1, "storage_file": 1},
  "access": [
    {"alias": "chat", "type": "flow", "ref": 1, "resource_name": "Chat Bot", "actions": ["run", "sessions.read", "sessions.stop"]}
  ],
  "secret_slots": [
    {
      "name": "OPENAI_API_KEY",
      "description": "OpenAI API key used by ...",
      "secret_name": "CHAT_BOT__OPENAI_API_KEY",
      "destinations": [
        {"resource_type": "llm_config", "name": "Chat Bot GPT-4o mini", "provider": "openai", "host": null},
        {"resource_type": "embedding_config", "name": "Chat Bot embeddings", "provider": "openai", "host": null}
      ]
    }
  ],
  "code_review_items": [],
  "has_knowledge": true,
  "ui_asset_count": 2,
  "warnings": [
    "This plugin runs its own code in a sandboxed page. The page can use what is listed below with the permissions of whoever opens it, and anything it can see could be sent to the plugin's author.",
    "Knowledge is indexed in the background after install. The plugin shows 'Preparing knowledge' until indexing finishes."
  ],
  "missing_permissions": [],
  "conflicts": [],
  "can_install": true
}
```

| Field | Notes |
|---|---|
| `contents[]` | `name` for a secret is the org secret that will be created; for a storage file, the org storage path. `documents` only on `source_collection`. |
| `access[].ref` | int, the flow's id inside the plugin file (not a database id yet). |
| `secret_slots[].destinations` | Where the slot's value will be sent, read from the plugin file. Show it next to the slot's input, and make a non-null `host` stand out: the key goes to that host, not to the provider. See "Secret slot destinations". |
| `code_review_items` | Same item shape as `POST /api/graphs/import/inspect/` → `review_items` (python tools, MCP tools, flow nodes with code). Non-empty means show the code warning. |
| `warnings` | Strings to show in the review step, in order. The UI warning (first, text above) is present whenever `plugin.has_ui`. The code warning ("This plugin contains Python code that will run in your organization's sandbox. Review it before installing.") follows whenever `code_review_items` is non-empty. |
| `missing_permissions` | `[{"resource_type": "secrets", "action": "create"}]`. Install would answer 403 `plugin_install_forbidden`. |
| `conflicts` | Same items as the 409 `plugin_resource_conflict` `errors`. |
| `can_install` | `missing_permissions` and `conflicts` are both empty. |

Errors: 400 `invalid_plugin`, 400 `invalid` (no file), 403, 409 `plugin_already_installed`
(the re-drop case: show "already installed {installed_version}").

## POST `/api/plugins/install/`

Installs everything in one transaction: all or nothing.

Request: `multipart/form-data`

| Field | Required | Notes |
|---|---|---|
| `file` | yes | Same zip as inspect. The server validates it again from scratch. |
| `secrets` | when the plugin declares slots | A **JSON object string**, slot name → value, exactly one entry per declared slot: `{"OPENAI_API_KEY":"sk-..."}`. |

Use `reportProgress` / `HttpEventType.UploadProgress` for the upload bar; the
server answers once everything is written.

Response **201**: `PluginDetail`. `status` is `preparing` when the plugin has
knowledge (indexing runs in the background), otherwise `ready`.

Errors: 400 `invalid_plugin`, 400 `invalid_plugin_secrets`, 400 `invalid`, 403
`permission_denied`, 403 `plugin_install_forbidden`, 409 `plugin_already_installed`,
409 `plugin_resource_conflict`.

While `status` is `preparing`, poll `GET /api/plugins/{id}/` (every 5 s) until it
becomes `ready` or `needs_attention`.

## POST `/api/plugins/{id}/suspend/`

No body. Turns the plugin fully off: its flows refuse to start by any route, its
agents and tools are unusable, ui-session answers 409. Live sessions of its flows
are stopped after the change commits. Idempotent.

Response 200: `PluginDetail` with `status: "suspended"`, `suspended: true`,
`suspended_at` set.

## POST `/api/plugins/{id}/resume/`

No body. Reverses suspend. Idempotent.

Response 200: `PluginDetail` with `suspended: false`, `suspended_at: null`, and
`status` equal to `state`.

## POST `/api/plugins/{id}/retry/`

No body. Restarts indexing of every knowledge collection that did not finish.
Their indexing status is reset to "new" first, so the next poll does not read the
old failure before the knowledge service picks the job up.

Response 200: `PluginDetail` with `status: "preparing"`. If indexing cannot even be
started (unreadable key, knowledge service down), the response already shows
`status: "needs_attention"` with the reason.

Errors: 409 `plugin_suspended`, 409 `plugin_not_retryable` (status is not
`needs_attention`).

## POST `/api/plugins/{id}/secrets/`

Re-enter one or more slot values (for example a wrong API key). Each named slot
gets a fresh secret under the same name, bound where the old one was.

Request: `application/json`

```json
{"secrets": {"OPENAI_API_KEY": "sk-new"}, "retry_indexing": true}
```

| Field | Required | Notes |
|---|---|---|
| `secrets` | yes | Object, slot name → value. At least one entry; only declared slots; values non-blank, at most 4096 characters. |
| `retry_indexing` | no (default `false`) | Also run retry when the plugin needs attention. |

Needs `plugins:update` **and** `secrets:create`, otherwise 403 `permission_denied`.

A slot whose secret still exists keeps every binding of it, including the
organization's own rows that use it. A slot whose secret was deleted
(`configured: false`) gets a new secret bound as the plugin file binds it. With
`retry_indexing: true` the retry is skipped (no error) while the plugin is suspended.

Response 200: `PluginDetail`.

Errors: 400 `invalid_plugin_secrets` (also when the slot's secret name is now taken
by another secret of the organization; an empty `secrets` object gives one item with
`"slot": ""`), 403.

## GET `/api/plugins/{id}/delete-preview/`

What deleting would remove. Writes nothing.

Response 200:

```json
{
  "plugin": {"id": 7, "plugin_id": "chat-bot", "name": "Chat Bot", "version": "0.1.0"},
  "resources": [
    {"type": "flow", "resource_id": 42, "name": "Chat Bot", "exists": true},
    {"type": "storage_file", "resource_id": 310, "name": "plugins/chat-bot/tone-guide.md", "exists": true}
  ],
  "resource_counts": {"flow": 1, "agent_definition": 1, "surface": 1, "llm_config": 1, "embedding_config": 1, "secret": 1, "source_collection": 1, "storage_file": 1},
  "session_count": 12,
  "live_session_count": 0,
  "affected_resources": {"flow": 1, "sessions": 12, "agent_definitions": 1, "surfaces": 1, "llm_configs": 1, "embedding_configs": 1, "secrets": 1, "knowledge_collections": 1, "knowledge_documents": 2, "storage_files": 1},
  "external_usages": [
    {
      "type": "flow",
      "resource_id": 42,
      "name": "Chat Bot",
      "used_by": [{"type": "flow", "resource_id": 77, "name": "My support flow"}]
    }
  ],
  "missing_permissions": [{"resource_type": "flows", "action": "delete"}]
}
```

| Field | Notes |
|---|---|
| `resources` | Rows that will be deleted; rows the org already deleted are listed with `exists: false` and skipped. |
| `session_count` | Run history of the plugin's flows that is deleted with them. |
| `live_session_count` | Sessions that will be stopped first. |
| `affected_resources` | Friendly-name counts of every row the delete cascades to, the same keys the organization delete preview uses (feed it to `delete-impact-message.util.ts`). |
| `missing_permissions` | `[{"resource_type": "<rbac code>", "action": "delete"}]`, sorted by `resource_type`; `[]` when nothing is missing. Non-empty means `DELETE` would answer 403 `plugin_delete_forbidden`: block the confirm button and name what is missing. Same item shape as inspect's `missing_permissions`. |
| `external_usages` | The org's **own** resources (not installed by the plugin) that reference a plugin resource and will lose it, e.g. a user flow embedding the plugin flow as a subflow. Empty array when none. Reported references: flow as subflow; agent in a flow's task or agent node; surface as an agent's default surface; LLM config of an agent; python / MCP tool, knowledge collection or storage file on a surface; storage file attached to a flow; secret of an LLM / embedding config or MCP tool. `used_by[].type` uses the resource type keys. |

A custom `llm_model` / `embedding_model` that one of the organization's own
configs uses is **kept** on delete (deleting it would cascade to that config), so it
is not listed in `resources` / `resource_counts`.

## DELETE `/api/plugins/{id}/`

Removes everything the plugin installed (including user edits to those rows and
their flows' run history), then the plugin itself. The plugin is suspended first, so
nothing can start while it is removed; its flows' live sessions are stopped as the
flows are deleted.

Besides `plugins:delete`, the caller needs **delete on the RBAC resource type of every
row that would be removed** (mirror of install needing create on every bundled type).
Rows the organization already deleted, and custom models kept because the
organization's own configs use them, need nothing. The plugin's rows map to RBAC types as:

| Plugin row type | RBAC `resource_type` |
|---|---|
| `flow` | `flows` |
| `agent_definition` | `agents` |
| `surface` | `surfaces` |
| `python_code_tool`, `mcp_tool` | `tools` |
| `webhook_trigger` | `webhooks` |
| `llm_config`, `embedding_config`, `llm_model`, `embedding_model` | `llm_configs` |
| `secret` | `secrets` |
| `source_collection` | `knowledge_sources` |
| `storage_file` | `files` |

The check runs before anything is written: a refused delete leaves the plugin
installed and not suspended. (In the rare case the plugin gained a row of a new type
between that check and the delete, the delete is still refused, but the plugin stays
suspended.)

Response **204**, no body.

Errors: 403 `permission_denied` (no `plugins:delete`), 403 `plugin_delete_forbidden`
(`errors` lists what is missing, the same list delete-preview's `missing_permissions`
shows), 404.

## POST `/api/plugins/{id}/ui-session/`

Opens the plugin's page. No body.

Response 200:

```json
{
  "url": "/api/plugin-ui/eyJwbHVnaW4iOjd9:1t2abc:Xyz.../index.html",
  "token": "eyJwbHVnaW4iOjd9:1t2abc:Xyz...",
  "expires_in": 600,
  "bridge_version": 1,
  "plugin": {"id": 7, "plugin_id": "chat-bot", "name": "Chat Bot", "version": "0.1.0"},
  "access": [
    {"alias": "chat", "type": "flow", "actions": ["run", "sessions.read", "sessions.stop"], "resource_id": 42}
  ]
}
```

| Field | Notes |
|---|---|
| `url` | Relative; always starts with `/api/plugin-ui/`. Set it as the iframe `src` (the host must refuse anything else). |
| `token` | Signed, reusable until it expires so the page's relative `<script src>` / `<link href>` load; carries no user credentials. |
| `expires_in` | Seconds. Request a new session to reopen the page after expiry. |
| `access` | The plugin's access list resolved to database ids, for the bridge's access policy. An entry whose flow was deleted has `resource_id: null` and must be treated as forbidden. |

Errors: 403, 404, 409 `plugin_suspended`, 409 `plugin_not_ready`, 409 `plugin_has_no_ui`.

## GET `/api/plugin-ui/{token}/{path}`

Serves one file of the plugin's page. Loaded by the sandboxed iframe, so it takes
no `Authorization` header and never sets cookies.

- 200: the file bytes, with
  - `Content-Type`: `text/html; charset=utf-8` (.html), `text/javascript; charset=utf-8` (.js),
    `text/css; charset=utf-8` (.css), `image/svg+xml` (.svg), `image/png` (.png),
    `application/json` (.json)
  - `Content-Security-Policy: sandbox allow-scripts; default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'`
  - `X-Content-Type-Options: nosniff`
  - `Cache-Control: no-store`
  - `Referrer-Policy: no-referrer`
  - `Cross-Origin-Resource-Policy: cross-origin` (the sandboxed page has an opaque origin, so `same-origin` would block its own subresources; the token in the URL is the protection)
  - `X-Frame-Options: SAMEORIGIN`
- 404 with an empty body for **any** failure: expired or forged token, unknown
  path, `../` in the path (or any other path that is not exactly the file's path,
  such as `./x` or `a//b`), plugin suspended or not ready, or the token's user no
  longer holding `plugins:use`.

What the browser receives behind the stack's nginx gateway (the `/api` location
adds the server-wide headers on top of the ones above): `X-Frame-Options:
SAMEORIGIN` once (nginx hides Django's and adds its own), `X-Content-Type-Options:
nosniff` twice (harmless), `Referrer-Policy` twice (`no-referrer` then nginx's
`strict-origin-when-cross-origin`; browsers apply the **last**, so the effective
policy is `strict-origin-when-cross-origin`), plus nginx's `Permissions-Policy` and the
SPA's `Content-Security-Policy-Report-Only` (report-only, not enforced). The
enforced `Content-Security-Policy`, `Cache-Control` and `Cross-Origin-Resource-Policy`
pass through unchanged.

## Secret slot destinations

A bundled config's or MCP tool's endpoint can point anywhere, so the review step and
the secrets dialog show where each slot's value will be sent before the admin types it.

```json
{"resource_type": "embedding_config", "name": "Chat Bot embeddings", "provider": "openai", "host": "embeddings.example.com"}
```

| Field | Type | Notes |
|---|---|---|
| `resource_type` | enum | `llm_config` \| `embedding_config` \| `mcp_tool`. |
| `name` | string | The config's name / the MCP tool's name. |
| `provider` | string or null | Provider name of the config's model (`"openai"`, ...); always `null` for `mcp_tool`. |
| `host` | string or null | Hostname of the endpoint the value is sent to, lower-case, without scheme, port or path. **`null` means the provider's standard endpoint.** For an LLM config: its model's `base_url`, else the config's own `base_url`; for an embedding config: its model's `base_url`; for an MCP tool: its server URL (the `transport` field). A custom endpoint whose host cannot be parsed is returned as written, never as `null`. |

Order: `llm_config` entries, then `embedding_config`, then `mcp_tool`. One entry per
resource, so a slot bound to two resources has two entries. `[]` when nothing uses the slot.

Where the list comes from:
- **Inspect:** the plugin file's `secret_bindings` and `resources.json`. Nothing is written.
- **Plugin object** (list and detail): what a value entered **now** would reach, as
  `POST /secrets/` would bind it. While the slot's secret exists: every LLM config,
  embedding config and MCP tool of the organization bound to that secret, including
  the organization's own rows and later edits. While it is deleted (`configured:
  false`): the plugin's own rows the plugin file binds the slot to, that still exist.

## Suspended plugins and other endpoints

While a plugin is suspended, every run of its flows is refused before a session is
created, whatever starts it (manual run, webhook, Telegram, schedule, the subflow
tool), and so is a run of the organization's own flow that embeds a plugin flow as a
subflow at any depth. `POST /api/run-session/` answers **409** with the envelope
`{"code": "plugin_suspended", "message": "Plugin 'Chat Bot' is suspended. ..."}` (not
the endpoint's usual `{"error": ...}` 400). A flow of the organization that uses a
suspended plugin's agent or tool starts, then fails while building its session
(session status `error`, same 409 from `run-session`).

## What the server rejects (400 `invalid_plugin`)

Listed so the install dialog can explain failures; the `errors[].message` texts
already say which rule failed.

- Not a zip; zip over 20 MB, over 200 entries or over 50 MB unpacked; an unsafe
  member name (`../`, absolute path); a blocked executable or archive type.
- Anything at the zip root other than `plugin.json`, `resources.json`,
  `knowledge/`, `files/`, `ui/`. A zip of the plugin folder itself (one top folder
  holding `plugin.json`) is accepted; `__MACOSX/` and `.DS_Store` are ignored.
- `plugin.json`: unknown keys anywhere (so a secret slot with a `value` is refused),
  unsupported `format_version` / `bridge` (both must be `1`), bad `id`, `version`,
  slot name or alias, duplicate slots / aliases / knowledge names / file paths,
  a binding to an undeclared slot or through the wrong field, access actions other
  than `run`, `sessions.read`, `sessions.stop`, access to anything but a flow,
  any `ref` that is not an entity of `resources.json`.
- `resources.json`: not a Flow export, a newer export version than the server
  reads, entity types a plugin may not carry, knowledge nodes bound to a
  collection, Python code that reads secrets by name (`get_secret("NAME")`).
- Knowledge documents missing, outside `knowledge/`, or of an unsupported type;
  storage files missing or outside `files/`.
- UI files other than `.html .js .css .svg .png .json`, more than 50 of them or
  over 5 MB in total; `ui.entry` not an `.html` file inside `ui/`; an icon that is
  not a real PNG/SVG or is over 64 KB.
