# Bulk Delete

Bulk deletion is available for seven resources: **Flows** (`Graph`,
`GraphVersion`), **LLM Configs**, **Embedding Configs**, and the three
**realtime voice configs** (`OpenAIRealtimeConfig`, `ElevenLabsRealtimeConfig`,
`GeminiRealtimeConfig`). All seven share one request contract and one response
shape, with no per-entity variation.

Every one of them is guarded by a permission-aware "in use" check: an entity
referenced from somewhere the caller **cannot see** is skipped rather than
deleted, and nothing about the hidden reference is disclosed. The same guard
backs single-object `DELETE` on these resources, so it cannot be bypassed by
deleting one id at a time.

Base URL in examples: `http://localhost:8000`.

---

## Quick reference

| Method | Path | Required permission |
|---|---|---|
| POST | `/api/graphs/bulk-delete/` | `FLOWS.DELETE` |
| POST | `/api/graph-versions/bulk-delete/` | `FLOWS.DELETE` |
| POST | `/api/llm-configs/bulk-delete/` | `LLM_CONFIGS.DELETE` |
| POST | `/api/embedding-configs/bulk-delete/` | `LLM_CONFIGS.DELETE` |
| POST | `/api/openai-realtime-configs/bulk-delete/` | `LLM_CONFIGS.DELETE` |
| POST | `/api/elevenlabs-realtime-configs/bulk-delete/` | `LLM_CONFIGS.DELETE` |
| POST | `/api/gemini-realtime-configs/bulk-delete/` | `LLM_CONFIGS.DELETE` |

`X-Organization-Id` is required on every endpoint above, same as any other
active-context resource endpoint — see
[roles_and_permissions.md](../rbac/roles_and_permissions.md#the-x-organization-id-header).
The realtime configs are gated under the `LLM_CONFIGS` resource type rather
than a type of their own.

---

## Request

### Body

```json
{ "ids": [1, 2, 3] }
```

- `ids` — required, 1–500 positive integers, cannot be empty. A duplicate id is
  handled once.

`400` on an empty, oversized, or malformed `ids` list. An oversized list is
rejected before its items are checked, so it costs one error, not one per item.

### `dry_run` — a query parameter

```
POST /api/graphs/bulk-delete/?dry_run=true
```

Runs every check and reports what would happen, without deleting anything. It
does **not** relax the in-use guard: an id that would be blocked is still
reported as blocked. A value that is not a clear boolean is rejected with `400`
rather than silently read as `false`:

- unparseable — `?dry_run=maybe`;
- blank — `?dry_run` or `?dry_run=`;
- repeated — `?dry_run=true&dry_run=false`.

> ⚠️ **`dry_run` must be in the query string.** A `dry_run` field sent in the
> request *body* is ignored, and the call runs as a **real delete**. There is
> no error to warn you. If you are adapting an older client that put
> `{"dry_run": true}` in the body, move it to `?dry_run=true`.

---

## Response shape

A dry run on realtime voice configs, whose usage is a single `agents` bucket.
The caller cannot read agents. Nothing uses config `5`. Config `6` is used by an
agent, which the caller cannot see, so `6` is blocked, and its bucket looks
exactly like `5`'s.

```json
{
  "dry_run": true,
  "deleted_count": 0,
  "deleted_ids": [],
  "deletable_ids": [5],
  "not_found_ids": [99],
  "skipped": [{ "id": 6, "reason": "in_use_restricted" }],
  "usage": {
    "5": {
      "blocked": false,
      "by_resource_type": [
        {
          "resource_type": "agents",
          "visible_count": 0,
          "visible_sample": [],
          "truncated": false
        }
      ]
    },
    "6": {
      "blocked": true,
      "by_resource_type": [
        {
          "resource_type": "agents",
          "visible_count": 0,
          "visible_sample": [],
          "truncated": false
        }
      ]
    }
  }
}
```

- `deletable_ids` — ids that passed every check. Populated in **both** modes: it
  answers "what would go".
- `deleted_ids` / `deleted_count` — ids actually removed. **Always empty / `0`
  on a dry run**, so a preview can never be mistaken for a deletion.
- `not_found_ids` — ids that don't exist, belong to another organization, or are
  not deletable by this organization. All of these land here identically — the
  cases are deliberately indistinguishable, so existence is never leaked.
- `skipped` — ids that exist but were left alone, each with a `reason`:
  - `in_use_restricted` — referenced by something the caller cannot see;
  - `protected` — refused by a database-level delete guard at delete time.
- `usage` — keyed by id. **Populated on a dry run only.** A real delete returns
  `usage: {}`: the key is always present, so the shape never varies, but the
  report itself is the preview payload.
  - Keys are **strings** (JSON object keys always are), while every other id
    field is an integer.
  - Every id that was checked gets an entry, with one bucket per resource type
    the entity can be referenced from — including ids nothing references, whose
    buckets all report `visible_count: 0`. The bucket list is fixed per entity:
    see [Per-entity usage detection](#per-entity-usage-detection).

Every resource returns exactly this shape — including `GraphVersion`, which
nothing references: it has no buckets, so its `skipped` is always `[]` and its
usage entries always have `by_resource_type: []`.

### A usage sample entry

```json
{ "resource_type": "agents", "kind": "agent_definition", "id": 12, "name": "Support bot" }
```

`kind` names the referencing entity's own type, which `resource_type` alone
cannot: the `agents` bucket merges two different tables whose ids overlap, so
`kind` is what tells `Agent #5` from `AgentDefinition #5`. Values:

| `kind` | Entity |
|---|---|
| `flow` | a Flow (`Graph`) |
| `agent` | a legacy agent (`tables.Agent`) |
| `agent_definition` | an agent (`agents.AgentDefinition`) |
| `crew` | a legacy crew (`tables.Crew`) |
| `collection` | a knowledge source collection |

### Status code

`200` when every id was handled as requested; `207 Multi-Status` when any id was
not found or skipped — including when *every* id was blocked. The same rule
applies to all seven resources and to dry runs.

---

## The `in_use_restricted` guard

An entity is **blocked** when something references it that the caller **cannot
see** — specifically, the caller lacks `READ` on the referencing row's own
resource type in the active organization. Visibility is all-or-nothing per
organization: if the caller can read the resource type at all, every reference
is visible; if not, none are. There is no per-row ACL.

Blocked ids are reported without disclosing what is blocking them:
`visible_count` and `visible_sample` only ever describe references the caller
can already see. A caller who cannot see any of them gets `visible_count: 0,
visible_sample: []` and no way to tell how many hidden references exist or what
they are. `visible_sample` is capped at 5 items (`truncated: true` when more
visible items exist beyond that) and sorted by `kind`, then `id`, so the same
references come back in the same order on every call.

The same parent reached through several paths counts **once** — a crew naming
one LLM config as its manager, memory and planning model is one reference, and
a flow reaching a config through both a decision-table node and an assistant is
one flow.

### Deleting something whose usage you *can* see is allowed

This is deliberate. The guard exists to prevent **information disclosure** —
you may not delete what you cannot see — not to protect you from your own
choices. If you can see every reference, the delete proceeds, and the
referencing rows keep existing with the field cleared (every relationship here
is `SET_NULL`).

**The server does not enforce a confirmation step.** There is no `force` flag
and no confirmation token: nothing stops a client from deleting without looking
at `usage` first. A client that wants to warn its user must run the call with
`?dry_run=true` first, show the reported `usage`, and only then send the real
delete. That obligation sits with the client.

### Single-object `DELETE`

Single `DELETE` on any of the seven resources runs the exact same check and
responds `403` (message `in_use_restricted`) when blocked. For `GraphVersion`
the check can never fire. As in bulk, the check and the delete run in one
transaction that holds a lock on the row, so a reference added between them
cannot be silently cleared.

---

## Per-entity usage detection

### Graph

Checked reference: `SubGraphNode.subgraph` — a `Graph` embedded as a sub-flow
inside another `Graph`. One bucket, `flows`.

Usage is checked before anything in the batch is deleted. So when a caller
without `FLOWS.READ` sends a flow together with a sub-flow it embeds, the parent
is deleted but the sub-flow is skipped as `in_use_restricted`: at check time,
the parent still referenced it. Retrying the sub-flow alone then succeeds.

### GraphVersion

Nothing in the schema holds a reference to a `GraphVersion` — a `Graph` has no
"current version" pointer, and restoring or branching from a version reads its
snapshot at call time without keeping a link back to it. There is nothing to
check and nothing can block it.

### LLM Config

Four buckets, each merged from several sources:

- `agents` — `Agent.llm_config` / `fcm_llm_config` (`kind: agent`) and
  `AgentDefinition.llm_config` / `fcm_llm_config` (`kind: agent_definition`).
- `projects` — `Crew.manager_llm_config`, `memory_llm_config`,
  `planning_llm_config` (`kind: crew`).
- `flows` — `ClassificationDecisionTableNode.default_llm_config`,
  `ClassificationDecisionTablePrompt.llm_config` and `FlowAssistant.llm_config`.
  The sample names the containing flow, not the node, prompt or assistant row.
- `knowledge_sources` — `GraphRag.llm`. The sample names the containing
  collection.

Not counted: `TemplateAgent` fields and the global default-model singletons,
which have no resource type to check the caller's visibility against.

### Embedding Config

Two buckets:

- `projects` — `Crew.embedding_config` (`kind: crew`).
- `knowledge_sources` — `GraphRag.embedder` and `NaiveRag.embedder`, merged. A
  collection with both kinds of RAG on the same embedder is one collection.

Not counted: the global default-model singletons
(`DefaultModels.memory_embedding_config`, `DefaultCrewConfig.embedding_config`),
which have no resource type to check the caller's visibility against.

### Realtime voice configs (OpenAI, ElevenLabs, Gemini)

One bucket, `agents`:

- `RealtimeAgent` — the realtime settings of a legacy agent (`kind: agent`);
- `RealtimeAgentDefinition` — the realtime settings of an agent
  (`kind: agent_definition`).

**Past voice sessions (`RealtimeAgentChat`) do not count.** A session records
which config it used, but it is a snapshot: it keeps its own copy of the voice,
language, wake word and the rest precisely so it survives the config being
deleted. Once the config is gone, a past session no longer shows which model it
used — the model name lives on the config — but it keeps its link to the agent.

### Legacy agents and crews still count

`tables.Agent` and `tables.Crew` are deprecated and have no API of their own,
but they still count as usage wherever they reference a config: existing flows
that contain a crew node keep executing, so deleting a config they rely on would
break those flows at run time.

---

## Soft delete

`Graph` and `GraphVersion` support soft delete, controlled by the
`DJANGO_SOFT_DELETE` setting (default **off**). Bulk delete honours it exactly
as single `DELETE` does: with it on, rows are marked deleted and remain
recoverable; with it off, they are removed.

---

## Error envelopes

Every error follows the project's standard envelope, `{status_code, code,
message}`.

### `400` — validation

Empty, oversized (over 500 items) or malformed `ids`, or a `dry_run` that is
unparseable, blank or repeated. Standard DRF field validation errors.

### `403 permission_denied` — missing the permission to delete

```json
{
  "status_code": 403,
  "code": "permission_denied",
  "message": "You do not have permission to bulk_delete llm_configs."
}
```

Raised before any usage logic runs when the caller lacks `DELETE` on the
endpoint's resource type in the active organization.

### `403 permission_denied` — blocked on single-object delete

```json
{
  "status_code": 403,
  "code": "permission_denied",
  "message": "in_use_restricted"
}
```

Raised by single `DELETE` on a resource the in-use guard would block. The bulk
endpoint never raises this — a blocked id is reported in `skipped` instead, so
one blocked id doesn't fail the rest of the batch.

---

## Notes for callers

| Behavior | Note |
|---|---|
| Before a destructive bulk action | Call with `?dry_run=true` first to see `deletable_ids`, `skipped` and `usage`, then show the user what will happen. The server will not ask for confirmation on its own. |
| `dry_run` placement | Query string only. In the body it is ignored and the call deletes for real. |
| `skipped` / `not_found_ids` | Partial success, not a request error — the response is `207`, not `4xx`/`5xx`. Surface per-id outcomes rather than treating the whole call as failed. |
| `usage` on a real delete | Always `{}`. Read usage from the dry run. |
| `usage.visible_sample` | Advisory and intentionally incomplete — it only lists references the caller can see, capped at 5. Don't render it as an exhaustive list of what's blocking a delete. |
| Cross-org and nonexistent ids | Both come back in `not_found_ids` with no way to tell them apart — this is deliberate, not a bug. |
