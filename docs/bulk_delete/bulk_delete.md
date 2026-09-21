# Bulk Delete

Bulk deletion is available for six resources: **Flows** (`Graph`,
`GraphVersion`), **LLM Configs**, **LLM Models**, **Embedding Configs**, and
**Embedding Models**. All six share one request contract
(`{ids, dry_run}`) and one response shape, and all but `GraphVersion` are
guarded by a permission-aware "in use" check — an entity referenced from
somewhere the caller cannot see is skipped rather than deleted, and nothing
about the hidden reference is disclosed. The same guard backs single-object
`DELETE` on these resources, so it cannot be bypassed by deleting one id at a
time.

Base URL in examples: `http://localhost:8000`.

---

## Quick reference

| Method | Path | Required permission |
|---|---|---|
| POST | `/api/graphs/bulk-delete/` | `FLOWS.DELETE` |
| POST | `/api/graph-versions/bulk-delete/` | `FLOWS.DELETE` |
| POST | `/api/llm-configs/bulk-delete/` | `LLM_CONFIGS.DELETE` |
| POST | `/api/llm-models/bulk-delete/` | `LLM_CONFIGS.DELETE` |
| POST | `/api/embedding-configs/bulk-delete/` | `LLM_CONFIGS.DELETE` |
| POST | `/api/embedding-models/bulk-delete/` | `LLM_CONFIGS.DELETE` |

`X-Organization-Id` is required on every endpoint above, same as any other
active-context resource endpoint — see
[roles_and_permissions.md](../rbac/roles_and_permissions.md#the-x-organization-id-header).
`LLMModel` and `EmbeddingModel` are gated under the `LLM_CONFIGS` resource
type rather than a type of their own — see
[roles_and_permissions.md](../rbac/roles_and_permissions.md#resource-scoping-coverage).

---

## Request body

Identical for all six endpoints:

```json
{ "ids": [1, 2, 3], "dry_run": false }
```

- `ids` — required, 1–500 positive integers, cannot be empty. A duplicate id
  is deleted once.
- `dry_run` — optional, default `false`. Runs every check and reports what
  would happen without calling delete on anything. It does **not** relax the
  in-use guard: an id that would be blocked is still reported as blocked.

`400` on an empty, oversized, or malformed `ids` list.

---

## Response shape

```json
{
  "dry_run": false,
  "deleted_count": 1,
  "deleted_ids": [5],
  "not_found_ids": [],
  "skipped_ids": [{ "id": 6, "reason": "in_use_restricted" }],
  "usage": {
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

- `deleted_ids` — ids that were (or, on `dry_run`, would be) deleted.
- `not_found_ids` — ids that don't exist, or belong to another organization.
  Both cases land here identically — a cross-org id is indistinguishable from
  a nonexistent one.
- `skipped_ids` — ids that exist but were left alone, each with a `reason`
  (`in_use_restricted` or, for models, `predefined` — see below).
- `usage` — keyed by id (as a string), one entry per id that was actually
  checked. Present even on a real, non-dry-run delete — it's informational,
  not preview-only.
- **`GraphVersion`'s response omits `skipped_ids` and `usage` entirely.**
  Nothing in the schema ever references a `GraphVersion`, so both fields
  would be permanently empty; they're left out instead of shipped as
  always-vacuous keys. Its response is just
  `{dry_run, deleted_count, deleted_ids, not_found_ids}`.

**Status code:** `200` when nothing was skipped or not found; `207
Multi-Status` otherwise (for `GraphVersion`, whenever `not_found_ids` is
non-empty, since it has no `skipped_ids` concept).

---

## The `in_use_restricted` guard

Applies to `Graph`, `LLMConfig`, `LLMModel`, `EmbeddingConfig`, and
`EmbeddingModel` — not `GraphVersion` (see its own section below).

An entity is **blocked** when something else references it and the caller
cannot see that referencing row — specifically, lacks `READ` on the
referencing row's own resource type in the active organization. Visibility is
currently all-or-nothing per organization: if the caller can read the
resource type at all, every reference is visible; if not, none are. There is
no per-row ACL yet.

Blocked ids are reported without disclosing what is blocking them:
`visible_count` and `visible_sample` only ever describe references the
caller can already see — a caller who cannot see any of them gets
`visible_count: 0, visible_sample: []` and no way to tell how many hidden
references exist or what they are. `visible_sample` is capped at 5 items
(`truncated: true` when more visible items exist beyond that).

Single-object `DELETE` on any of these five resources runs the exact same
check and responds `403` (`code: permission_denied`, message
`in_use_restricted`) when blocked — so the guard cannot be bypassed by
deleting one id at a time instead of using bulk-delete.

---

## Per-entity usage detection

### Graph

Checked reference: `SubGraphNode.subgraph` — a `Graph` embedded as a
sub-flow inside another `Graph`. One usage bucket, `FLOWS`: blocked when a
parent flow embeds it and the caller cannot read `FLOWS`.

Deleting an unblocked graph nulls out the `subgraph` reference on any
`SubGraphNode` that isn't itself the graph being deleted.

### GraphVersion

Nothing in the schema holds a reference to a `GraphVersion` — a `Graph` has
no "current version" pointer, and restoring or branching from a version
reads its snapshot at call time without keeping a link back to it. The guard
can never fire, so there is nothing to check, skip, or report (see the
response-shape note above).

### LLM Config

Four usage buckets, merged from multiple sources each:

- `AGENTS` — `Agent.llm_config` / `Agent.fcm_llm_config`, and
  `AgentDefinition.llm_config` / `AgentDefinition.fcm_llm_config`.
- `PROJECTS` — `Crew.manager_llm_config`, `Crew.memory_llm_config`,
  `Crew.planning_llm_config`.
- `FLOWS` — `ClassificationDecisionTableNode.default_llm_config`,
  `ClassificationDecisionTablePrompt.llm_config`, and
  `FlowAssistant.llm_config`. The sample shown is the containing flow, not
  the individual node/prompt/assistant row.
- `KNOWLEDGE_SOURCES` — `GraphRag.llm`. The sample shown is the containing
  storage collection.

An LLM config is blocked if **any** bucket has a reference the caller cannot
see. These are all `SET_NULL` foreign keys, so an unblocked delete leaves the
referencing rows in place with the field cleared rather than deleting them.

### LLM Model

`LLMConfig.model` is a `CASCADE` foreign key — deleting an `LLMModel` force-
deletes every `LLMConfig` row that uses it. Because of that, a plain
one-hop visibility check on the model→config link isn't enough: the real
risk is that a cascaded config is itself in use somewhere the caller can't
see (an agent, a crew, a flow, a knowledge source). The check is therefore
cascade-aware — it reuses the LLM Config usage check against every config
that would be cascade-deleted, and blocks the model if the model→config link
is hidden **or** any cascaded config is itself blocked.

Predefined models (global, not organization-owned) can never be deleted,
regardless of usage — they're skipped with reason `predefined` before usage
is even computed, and don't appear in the `usage` map at all.

### Embedding Config

Two usage buckets:

- `PROJECTS` — `Crew.embedding_config`.
- `KNOWLEDGE_SOURCES` — `GraphRag.embedder` and `NaiveRag.embedder`, merged.
  The sample shown is the containing storage collection.

Same all-or-nothing per-bucket visibility rule as LLM Config.

### Embedding Model

`EmbeddingConfig.model` is a `SET_NULL` foreign key — unlike LLM Model,
deleting the model only clears the reference on referencing configs, it
never cascade-deletes them. A plain one-hop check against `LLM_CONFIGS`
visibility is enough here; there is no cascaded-usage recursion.

Predefined models are protected the same way as predefined LLM Models.

---

## Error envelopes

Every error follows the project's standard envelope,
`{status_code, code, message}`.

### `400` — validation

Empty, oversized (over 500 items), or malformed `ids`. Standard DRF field
validation errors.

### `403 permission_denied` — missing the door-gate permission

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

Raised by `DELETE` on a single Graph, LLM Config, LLM Model, Embedding
Config, or Embedding Model that the in-use guard would block. The bulk
endpoint never raises this — a blocked id is reported in `skipped_ids`
instead, so one blocked id doesn't fail the rest of the batch.

---

## Notes for callers

| Behavior | Note |
|---|---|
| Before a destructive bulk action | Call with `dry_run: true` first to see `deleted_ids`, `skipped_ids`, and `usage` without deleting anything. |
| `skipped_ids` / `not_found_ids` | Partial success, not a request error — the response is still `207`, not `4xx`/`5xx`. Surface per-id outcomes rather than treating the whole call as failed. |
| `usage.visible_sample` | Advisory and intentionally incomplete — it only ever lists references the caller can see, capped at 5. Don't render it as an exhaustive list of what's blocking a delete. |
| Cross-org and nonexistent ids | Both come back in `not_found_ids` with no way to tell them apart — this is deliberate, not a bug. |
