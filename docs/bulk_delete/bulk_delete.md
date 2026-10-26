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
reported as blocked. A dry run always responds `200`. The value is parsed as a
standard DRF boolean; a value that is not a boolean (`?dry_run=maybe`) is
rejected with `400`.

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
{ "resource_type": "agents", "id": 12, "name": "Support bot" }
```

`resource_type` names the bucket; every id in a bucket points at the same kind
of entity (a flow, an agent or a knowledge source collection).

### Status code

A real delete responds `200` when every id was deleted and `207 Multi-Status`
when any id was not found or skipped — including when *every* id was blocked. A
dry run always responds `200`; its per-id outcome is in the body. The same rule
applies to all seven resources.

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
visible items exist beyond that) and sorted by `id`, so the same
references come back in the same order on every call.

The same parent reached through several paths counts **once** — an agent naming
one LLM config as both its primary and tool-call model is one reference, and a
flow reaching a config through both a decision-table node and an assistant is
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
responds `403` (code `in_use_restricted`) when blocked. For `GraphVersion`
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

When a flow embedded as a sub-flow is bulk-deleted, the parent flow's sub-flow
node is cleared, and restoring the sub-flow from the recycle bin does **not**
re-link it in the parent.

### GraphVersion

Nothing in the schema holds a reference to a `GraphVersion` — a `Graph` has no
"current version" pointer, and restoring or branching from a version reads its
snapshot at call time without keeping a link back to it. There is nothing to
check and nothing can block it.

### LLM Config

Three buckets, each merged from several sources:

- `agents` — `AgentDefinition.llm_config` / `fcm_llm_config`.
- `flows` — `ClassificationDecisionTableNode.default_llm_config`,
  `ClassificationDecisionTablePrompt.llm_config` and `FlowAssistant.llm_config`.
  The sample names the containing flow, not the node, prompt or assistant row.
- `knowledge_sources` — `GraphRag.llm`. The sample names the containing
  collection.

Not counted: `TemplateAgent` fields and the global default-model singletons,
which have no resource type to check the caller's visibility against.

### Embedding Config

One bucket, `knowledge_sources` — `GraphRag.embedder` and `NaiveRag.embedder`,
merged. A collection with both kinds of RAG on the same embedder is one
collection.

Not counted: the global default-model singletons
(`DefaultModels.memory_embedding_config`, `DefaultCrewConfig.embedding_config`),
which have no resource type to check the caller's visibility against.

### Realtime voice configs (OpenAI, ElevenLabs, Gemini)

One bucket, `agents` — `RealtimeAgentDefinition`, the realtime settings of an
agent.

**Past voice sessions (`RealtimeAgentChat`) do not count.** A session records
which config it used, but it is a snapshot: it keeps its own copy of the voice,
language, wake word and the rest precisely so it survives the config being
deleted. Once the config is gone, a past session no longer shows which model it
used — the model name lives on the config — but it keeps its link to the agent.

---

## Soft delete and the recycle bin

What a bulk delete does to a row depends on the entity. There is no setting to
turn soft delete on or off: it is a property of the model.

| Entity | Result |
|---|---|
| Flow (`Graph`) | Moved to the recycle bin, restorable for the retention period (`DJANGO_RECYCLE_BIN_RETENTION_DAYS`). |
| Flow version (`GraphVersion`) | Soft-deleted. It has no recycle-bin tab, so it cannot be restored from the UI. |
| LLM, embedding and voice configs | Deleted permanently. |

A bulk-deleted flow is binned exactly as a single `DELETE` bins it, through
`move_to_recycle_bin`: the requesting user is recorded as who deleted it, so the
bin's "Deleted by" shows the same thing for both paths. A dry run deletes and
records nothing. Flow versions have no bin entry, so no deleter is recorded for
them.

Flows are binned one at a time, each in its own savepoint, so a row the database
refuses to delete is reported as `skipped` with reason `protected` without losing
the rest of the batch. A delete that would reach another organization's rows
(`CrossOrgCascadeError`) is different: it means the data holds a link no API path
creates, so it is not reported per id. The whole request fails with `409` and
nothing is deleted.

---

## Error envelopes

Every error follows the project's standard envelope, `{status_code, code,
message}`.

### `400` — validation

Empty, oversized (over 500 items) or malformed `ids`, or a `dry_run` that is not
a boolean. Standard DRF field validation errors.

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

### `403 in_use_restricted` — blocked on single-object delete

```json
{
  "status_code": 403,
  "code": "in_use_restricted",
  "message": "This item is used somewhere you don't have access to, so it can't be deleted."
}
```

Raised by single `DELETE` on a resource the in-use guard would block. The bulk
endpoint never raises this — a blocked id is reported in `skipped` instead, so
one blocked id doesn't fail the rest of the batch.

A fixed business rule on the row, not a change in the caller's own
permissions — the frontend must not treat it as stale permissions (that is
what `permission_denied` above is for).

### `409 cross_org_cascade` — the delete would reach another organization

```json
{
  "status_code": 409,
  "code": "cross_org_cascade",
  "message": "This item is linked to data it can't be deleted with. Nothing was deleted. Contact an administrator."
}
```

Raised by bulk delete of flows and flow versions, and by single `DELETE` of a
flow, when a row's soft delete would change another organization's rows. It
means the data holds a link no API path creates, so it is not reported per id:
the whole request rolls back and nothing is deleted. The message names neither
the row nor the other organization.

---

## Notes for callers

| Behavior | Note |
|---|---|
| Before a destructive bulk action | Call with `?dry_run=true` first to see `deletable_ids`, `skipped` and `usage`, then show the user what will happen. The server will not ask for confirmation on its own. |
| `dry_run` placement | Query string only. In the body it is ignored and the call deletes for real. |
| `skipped` / `not_found_ids` | Partial success, not a request error — a real delete responds `207`, not `4xx`/`5xx`; a dry run responds `200`. Surface per-id outcomes rather than treating the whole call as failed. |
| `usage` on a real delete | Always `{}`. Read usage from the dry run. |
| `usage.visible_sample` | Advisory and intentionally incomplete — it only lists references the caller can see, capped at 5. Don't render it as an exhaustive list of what's blocking a delete. |
| Cross-org and nonexistent ids | Both come back in `not_found_ids` with no way to tell them apart — this is deliberate, not a bug. |
