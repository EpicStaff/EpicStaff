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
- **Crew** — `manager_llm_config`, `memory_llm_config`, `embedding_config`, `agents`.
- **Configs → model** (hybrid targets — shared built-ins allowed, other orgs' custom rows rejected):
  `LLMConfig.model`, `EmbeddingConfig.model`, `RealtimeConfig.realtime_model`,
  `RealtimeTranscriptionConfig.realtime_transcription_model`.
- **Tool configs** (hybrid target): `PythonCodeToolConfig.tool`; `PythonCodeToolConfigField.tool`.
- **Graph nodes**: `CodeAgentNode.llm_config`, `SubGraphNode.subgraph`, `CrewNode.crew`.
- **Label** — `parent`.
- **Bulk save** (`POST /api/graphs/{pk}/save/`) enforces the same on every referenced entity — see
  `bulk_save/BULK_SAVE_API.md`.
- **Storage / files** — every operation is scoped to the active org (files are keyed by org, gated by
  the `FILES` permission). `add-to-graph` / `graph-files` reject a graph id outside the active org
  exactly like a missing one; cross-org file `move` / `copy` is superadmin-only. See
  `storage/STORAGE_API_REFERENCE.md`.

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
