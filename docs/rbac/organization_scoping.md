# Organization Scoping (resource data isolation)

How the backend keeps one organization's data invisible and unreachable to another. This is the
**data isolation** layer; it is orthogonal to **authorization** (which *verbs* a role may perform —
see `roles_and_permissions.md`). A caller can have permission to create agents yet still be unable
to touch, or even reference, another org's data.

## Active organization

Every resource request carries the active organization in the `X-Organization-Id` header (see
`roles_and_permissions.md` for the header contract). All reads and writes are performed as that org.

## Ownership model

Every org-scoped resource is one of:

- **Strict** — owned by exactly one org (an `org` foreign key). Examples: Graph, Agent, Crew, Task,
  the config rows (`LLMConfig`, `EmbeddingConfig`, `RealtimeConfig`, `RealtimeTranscriptionConfig`),
  `McpTool`, `PythonCodeToolConfig`, `SourceCollection`, `Label`.
- **Hybrid** — either a **shared built-in** (visible to every org, no owning org) **or** an org's own
  **custom** row (org-private). Examples: `LLMModel` / `EmbeddingModel` / `RealtimeModel` /
  `RealtimeTranscriptionModel` (built-ins have `is_custom = false`); `PythonCodeTool` (built-ins have
  `built_in = true`).

## Read isolation

- List endpoints return only the active org's rows — plus the shared built-ins for hybrid resources.
- Fetching another org's row by id returns **404**, indistinguishable from a truly missing id.

## Write / reference isolation

When a write **references another resource by id** (a foreign key, or an id inside a list/string),
the referenced id must resolve within the active org's visibility:

- **strict** target → must be an active-org row;
- **hybrid** target → must be a shared built-in **or** an active-org custom row.

A reference to another org's row is rejected as a validation error —
`Invalid pk "<id>" - object does not exist.` (HTTP 400). Cross-org and non-existent references are
**indistinguishable** (no existence leak), and the write fails atomically, leaving no partial or
orphan row.

This rule is applied uniformly wherever such references appear, including (non-exhaustive):

- **Agent** — `llm_config`, `fcm_llm_config`, `knowledge_collection`, `rag`, `tool_ids`, and the
  nested realtime-agent's `realtime_config` / `realtime_transcription_config`.
- **Task** — `agent`, `crew`, `tool_ids`.
- **Crew** — `manager_llm_config`, `memory_llm_config`, `planning_llm_config`, `embedding_config`, `agents`.
- **Task** — context tasks must belong to the task's own crew (⇒ same org).
- **Graph** — `label_ids`.
- **Every graph-child node's `graph` FK** (crew/python/file-extractor/audio/subgraph/edge/
  conditional-edge/start/end/decision-table/webhook-trigger/telegram-trigger/schedule-trigger/note) is
  scoped, so a node cannot be created under, or repointed (on update) to, another org's graph.
- **Node-id references must live in the same graph** (⇒ same org): `Edge.start_node_id`/`end_node_id`,
  `DecisionTableNode.default_next_node_id`/`next_error_node_id`, and each decision-table condition
  group's `next_node_id`.
- **init-realtime** (`POST /api/init-realtime/`) requires `AGENTS.READ` and an `agent_id` in the active
  org.
- **Configs → model** (hybrid targets — shared built-ins allowed, other orgs' custom rows rejected):
  `LLMConfig.model`, `EmbeddingConfig.model`, `RealtimeConfig.realtime_model`,
  `RealtimeTranscriptionConfig.realtime_transcription_model`.
- **Tool configs** (hybrid target): `PythonCodeToolConfig.tool`; `PythonCodeToolConfigField.tool`.
- **Graph nodes**: `SubGraphNode.subgraph`.
- **Label** — `parent`.
- **Bulk save** (`POST /api/graphs/{pk}/save/`) enforces the same on every referenced entity — see
  `bulk_save/BULK_SAVE_API.md`.
- **Storage / files** — every operation is scoped to the active org (files are keyed by org, gated by
  the `FILES` permission). `add-to-graph` / `graph-files` reject a graph id outside the active org
  exactly like a missing one; cross-org file `move` / `copy` is superadmin-only. See
  `storage/STORAGE_API_REFERENCE.md`.

## Execution & platform endpoints

Some endpoints expose execution artifacts or platform-wide infrastructure that has no org column.
Their access rules:

- **`GET /api/python-code-result/{execution_id}/`** — superadmin only (results hold another org's
  stdout / `result_data`). The list endpoint `GET /api/python-code-result/` is removed (405).
- **`/api/realtime-session-items/`** — superadmin only, read-only (items hold conversation payloads
  including base64 audio, keyed by an opaque connection key with no org column).
- **`/api/ngrok-config/`** — superadmin only for read and write (holds the ngrok `auth_token`, a
  platform secret).
- **`/api/voice-settings/`** — superadmin only (holds the platform Twilio credentials).
- **`POST /api/run-python-code/`** — requires `TOOLS` · `UPDATE`, and the `python_code_id` must be
  visible to the active org (referenced by an org-owned tool — built-in tools are global — or by a
  node/edge in one of the org's graphs). A code id outside the active org is rejected like a missing
  one (`Invalid pk … - object does not exist.`, HTTP 400).
- **`GET /api/quickstart/`** — returns `last_config` (the org's most recent quickstart config) scoped
  to the active org; one org never sees another org's quickstart config.
- **`ngrok_webhook_config` on webhook triggers** — `NgrokWebhookConfig` is global platform infra (no
  `org` column). Only superadmins may assign it when creating/updating a webhook trigger (directly or
  via a webhook-trigger node); the field is dropped from non-superadmin input, so a normal user cannot
  bind a trigger to an arbitrary ngrok config by id. (Making ngrok per-org is tracked as tech debt.)

## Example

Active org **A**; org **B** owns `LLMConfig id 42`.

```http
POST /api/agents/
X-Organization-Id: <A>
{ "role": "r", "goal": "g", "backstory": "b", "llm_config": 42 }

HTTP 400 Bad Request
{ "llm_config": ["Invalid pk \"42\" - object does not exist."] }
```

The same request with an org-A config id (or, for a hybrid target, a shared built-in id) succeeds.
