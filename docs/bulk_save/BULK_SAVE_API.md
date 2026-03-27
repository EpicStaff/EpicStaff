# Bulk Save Flow — API Reference

## Overview

`POST /api/graphs/{pk}/save/`

This endpoint is the single write surface for the entire graph canvas. A single request can create new nodes, update existing ones, connect them with edges, and delete obsolete entities — all atomically. Nothing is written to the database unless every entity in the request passes validation.

---

## Key Concepts

### `id` vs `temp_id`

Every entity in the payload follows a simple rule to distinguish creates from updates:

| Field present | Meaning |
|---|---|
| No `id` (or `id: null`) | **Create** a new record |
| `id: <integer>` | **Update** the existing record with that database id |

`temp_id` is a completely separate concept. It is a client-generated UUID that you assign to a **new** node so that edges in the **same request** can reference it before the node has been written to the database and received a real id.

- `temp_id` is wire-only. It is stripped before any database write and is never stored.
- A `temp_id` must be a valid UUID v4.
- You only need `temp_id` on a node when an edge in the same request must point to that node.
- If both `id` and `temp_id` are supplied on the same node, the server ignores the `temp_id` entirely (it resolves the `id` path instead).

---

## Request

**Method:** `POST`
**URL:** `/api/graphs/{pk}/save/`
**Content-Type:** `application/json`

### Top-Level Payload Shape

All keys are optional. Omitting a key or passing an empty list for it means "no changes for this type."

```json
{
  "crew_node_list":                [],
  "python_node_list":              [],
  "file_extractor_node_list":      [],
  "audio_transcription_node_list": [],
  "llm_node_list":                 [],
  "start_node_list":               [],
  "end_node_list":                 [],
  "subgraph_node_list":            [],
  "decision_table_node_list":      [],
  "graph_note_list":               [],
  "webhook_trigger_node_list":     [],
  "telegram_trigger_node_list":    [],

  "edge_list":              [],
  "conditional_edge_list":  [],

  "deleted": {
    "crew_node_ids":                [],
    "python_node_ids":              [],
    "file_extractor_node_ids":      [],
    "audio_transcription_node_ids": [],
    "llm_node_ids":                 [],
    "start_node_ids":               [],
    "end_node_ids":                 [],
    "subgraph_node_ids":            [],
    "decision_table_node_ids":      [],
    "graph_note_list":              [],
    "webhook_trigger_node_ids":     [],
    "telegram_trigger_node_ids":    [],
    "edge_ids":                     [],
    "conditional_edge_ids":         []
  }
}
```

### Node List Items

Each item in any `*_node_list` array mirrors the payload of the corresponding single-node create/update endpoint, with two extra fields added:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | integer | No | Omit (or send `null`) to create. Pass the DB id to update. |
| `temp_id` | UUID string | No | Client-assigned UUID for new nodes. Used only so edges in this same request can reference the node. Never stored. |

All other fields follow the respective node serializer rules. See per-node notes below.

### Edge List Items (`edge_list`)

Regular edges connect two nodes. Each endpoint (start / end) is referenced by **exactly one** of a real db id or a temp id.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | integer | No | Omit to create a new edge; include to update an existing one. |
| `graph` | integer | Yes | The graph id (must match `{pk}` in the URL). |
| `start_node_id` | integer | Conditional | Real DB id of the start node. Required if `start_temp_id` is absent. |
| `start_temp_id` | UUID string | Conditional | `temp_id` of a new node in this same request. Required if `start_node_id` is absent. |
| `end_node_id` | integer | Conditional | Real DB id of the end node. Required if `end_temp_id` is absent. |
| `end_temp_id` | UUID string | Conditional | `temp_id` of a new node in this same request. Required if `end_node_id` is absent. |

**Rule:** For each end (start and end independently), provide exactly one of the `_node_id` or `_temp_id` variant. Providing both or neither is a validation error.

### Conditional Edge List Items (`conditional_edge_list`)

Conditional edges have a single source node and carry routing logic (a Python code reference).

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | integer | No | Omit to create; include to update. |
| `graph` | integer | Yes | The graph id. |
| `source_node_id` | integer | Conditional | Real DB id of the source node. Required if `source_temp_id` is absent. |
| `source_temp_id` | UUID string | Conditional | `temp_id` of a new node in this same request. Required if `source_node_id` is absent. |
| `python_code` | object | Yes | Nested dict with `code`, `entrypoint`, and `libraries`. |
| `input_map` | object | No | Default `{}`. |

### `deleted` Object

Every key in `deleted` is optional and defaults to an empty list. Pass a list of integer ids to delete. All ids are validated as belonging to the target graph — an id from a different graph is a validation error.

Edges are always deleted before nodes (to respect foreign key constraints), regardless of the order keys appear in the payload.

---

## Processing Model

The service performs a strict two-pass cycle:

**Pass 1 — Validation (no DB writes):**
1. Validate all deletion ids (must belong to this graph).
2. Validate every item in every node list against its serializer.
3. Validate every edge and conditional edge item, including node reference resolution.
4. Collect all errors across all entity types.

If any error is found anywhere, the entire request is rejected with HTTP 400 and the full error map. No database write occurs.

**Pass 2 — Atomic write (only if Pass 1 is clean):**
1. Delete all requested edges (before nodes).
2. Delete all requested nodes.
3. Save nodes (creates first, which populates the `temp_id → real id` map).
4. Save edges (temp references resolved from the map built in step 3).

The entire Pass 2 runs inside a single database transaction.

---

## Per-Node Notes

### CrewNode

Uses `crew_id` (integer, write-only) to assign the linked crew. Do **not** pass a nested `crew` object.

```json
{
  "graph": 12,
  "crew_id": 3,
  "node_name": "my_crew_node",
  "input_map": {},
  "output_variable_path": null,
  "metadata": {}
}
```

### PythonNode

`python_code` is a **nested object**, not an id. Pass the full code definition inline.

```json
{
  "graph": 12,
  "python_code": {
    "code": "def main(input): return input.upper()",
    "entrypoint": "main",
    "libraries": []
  },
  "node_name": "my_python_node",
  "input_map": {},
  "output_variable_path": "result",
  "metadata": {}
}
```

### DecisionTableNode

`condition_groups` is a nested list. On **update**, the server replaces all existing condition groups and their conditions wholesale — it does not patch them individually.

```json
{
  "graph": 12,
  "node_name": "router",
  "condition_groups": [
    {
      "group_name": "group_a",
      "group_type": "simple",
      "order": 0,
      "conditions": [
        {
          "condition_name": "cond_1",
          "condition": "variables.score > 50",
          "order": 0
        }
      ]
    }
  ]
}
```

### StartNode / EndNode

These have unique-per-graph constraints. Only one of each may exist per graph.

- `StartNode` fields: `graph`, `variables` (JSON, default `{}`), `metadata`.
- `EndNode` fields: `graph`, `output_map` (JSON, defaults to `{"context": "variables"}` if empty), `metadata`.

### NoteNode

Simple canvas annotation. Fields: `graph`, `content` (text), `metadata`.

---

## Responses

### HTTP 200 — Success

Returns the full serialized graph object (same shape as `GET /api/graphs/{pk}/`) reflecting the state after all writes.

```json
{
  "id": 12,
  "name": "My Flow",
  "crew_node_list": [...],
  "python_node_list": [...],
  "edge_list": [...],
  ...
}
```

### HTTP 400 — Validation Error

No database writes have occurred. The response body contains a structured error map keyed by the payload section that failed.

```json
{
  "errors": {
    "python_node_list": [
      {
        "index": 0,
        "errors": {
          "python_code": {
            "code": ["This field is required."]
          }
        }
      }
    ],
    "edge_list": [
      {
        "index": 1,
        "errors": "Provide exactly one of start_node_id or start_temp_id, not both."
      }
    ],
    "deleted": [
      "python_node_ids: IDs [99999] not found in graph 12"
    ]
  }
}
```

Error shape per section:

- **Node list errors** (`crew_node_list`, `python_node_list`, etc.): array of `{ "index": <int>, "errors": <object or string> }`. `index` is the zero-based position of the failing item in the submitted list.
- **Edge list errors** (`edge_list`, `conditional_edge_list`): same `{ "index", "errors" }` shape. May also include a top-level string for cross-edge reference failures (e.g. referencing a non-existent real node id).
- **Deletion errors** (`deleted`): array of plain strings, each naming the delete key and the invalid ids.

### HTTP 404 — Graph Not Found

Returned when `{pk}` does not match any graph in the database.

---

## Examples

### Example 1 — Create a New PythonNode

```json
POST /api/graphs/12/save/

{
  "python_node_list": [
    {
      "graph": 12,
      "python_code": {
        "code": "def main(input): return input.strip()",
        "entrypoint": "main",
        "libraries": []
      },
      "node_name": "text_cleaner",
      "input_map": { "input": "variables.raw_text" },
      "output_variable_path": "cleaned_text",
      "metadata": { "position": { "x": 300, "y": 200 } }
    }
  ]
}
```

No `id` is present, so a new `PythonNode` and its associated `PythonCode` record are created.

---

### Example 2 — Update an Existing CrewNode

```json
POST /api/graphs/12/save/

{
  "crew_node_list": [
    {
      "id": 5,
      "graph": 12,
      "crew_id": 7,
      "node_name": "support_crew",
      "input_map": { "ticket": "variables.ticket_text" },
      "output_variable_path": "crew_result",
      "metadata": { "position": { "x": 600, "y": 200 } }
    }
  ]
}
```

`id: 5` is present, so the server finds the existing `CrewNode` with that id (scoped to graph 12) and updates it. Note `crew_id`, not `crew`, is the write field.

---

### Example 3 — Delete Nodes and Edges

```json
POST /api/graphs/12/save/

{
  "deleted": {
    "edge_ids": [14, 15],
    "python_node_ids": [9]
  }
}
```

Edges 14 and 15 are deleted first (before the node), then `PythonNode` 9 is deleted. All three ids must belong to graph 12 or the entire request is rejected.

---

### Example 4 — Create a New Node and Wire an Edge to It in One Request

This is the primary use case for `temp_id`. The frontend assigns a UUID to the new node so the edge can reference it before the node has a real database id.

```json
POST /api/graphs/12/save/

{
  "python_node_list": [
    {
      "graph": 12,
      "temp_id": "aaaabbbb-1111-2222-3333-000000000001",
      "python_code": {
        "code": "def main(text): return text.lower()",
        "entrypoint": "main",
        "libraries": []
      },
      "node_name": "lowercaser",
      "input_map": {},
      "output_variable_path": null,
      "metadata": { "position": { "x": 500, "y": 100 } }
    }
  ],
  "edge_list": [
    {
      "graph": 12,
      "start_node_id": 1,
      "end_temp_id": "aaaabbbb-1111-2222-3333-000000000001"
    }
  ]
}
```

The server saves the `PythonNode` first, maps `temp_id → real_id`, then writes the edge using the real id. The `temp_id` is never stored.

The `start_node_id: 1` in the edge references an already-existing node (e.g. the `StartNode`), so no `start_temp_id` is needed for that end.

---

### Example 5 — Combined Create, Update, and Delete in One Request

```json
POST /api/graphs/12/save/

{
  "python_node_list": [
    {
      "graph": 12,
      "python_code": {
        "code": "def main(): return 'hello'",
        "entrypoint": "main",
        "libraries": []
      },
      "node_name": "greeter",
      "metadata": { "position": { "x": 200, "y": 300 } }
    }
  ],
  "crew_node_list": [
    {
      "id": 5,
      "graph": 12,
      "crew_id": 3,
      "node_name": "crew_renamed",
      "input_map": {},
      "output_variable_path": null,
      "metadata": { "position": { "x": 600, "y": 300 } }
    }
  ],
  "deleted": {
    "python_node_ids": [9],
    "edge_ids": [14]
  }
}
```

In one atomic transaction this request:
1. Deletes edge 14 and `PythonNode` 9.
2. Creates a new `PythonNode` ("greeter").
3. Updates `CrewNode` 5 with a new name.

If any of the three operations fail validation, none of the writes happen.

---

## Error Scenarios and Common Mistakes

| Mistake | Error |
|---|---|
| Sending `id` that does not exist in this graph | `{ "index": 0, "errors": "id=99999 not found in graph 12" }` |
| Sending both `start_node_id` and `start_temp_id` on the same edge | `{ "index": 0, "errors": "Provide exactly one of start_node_id or start_temp_id, not both." }` |
| `start_temp_id` value not matching any `temp_id` in the node lists | `{ "index": 0, "errors": "start_temp_id='...' does not match any temp_id in the node lists of this request." }` |
| Deleting a node id that belongs to a different graph | `"deleted": ["python_node_ids: IDs [42] not found in graph 12"]` |
| Missing required nested field (e.g. `python_code.code`) | `{ "index": 0, "errors": { "python_code": { "code": ["This field is required."] } } }` |
| `crew_id` instead of `crew` omitted / wrong field name | `{ "index": 0, "errors": { "crew_id": ["This field is required."] } }` |

---

## Atomicity Guarantee

All database writes for a single request execute inside one database transaction. If any write fails at the ORM level after validation has passed, the transaction is rolled back. The two-pass design means ORM-level failures are extremely rare — by the time writes begin, all data has already been validated.

---

## Key Files

| File | Description |
|---|---|
| `tables/views/model_view_sets.py` | `GraphViewSet.save_flow` action — HTTP boundary, input validation, error formatting, success response |
| `tables/serializers/graph_bulk_save_serializers.py` | `GraphBulkSaveInputSerializer`, per-node bulk serializers, `EdgeBulkSerializer`, `ConditionalEdgeBulkSerializer`, `DeletedEntitiesSerializer` |
| `tables/services/graph_bulk_save_service/service.py` | `GraphBulkSaveService` — two-pass validation and atomic write orchestration |
| `tables/services/graph_bulk_save_service/registry.py` | `NODE_TYPE_REGISTRY` — single source of truth mapping list keys, delete keys, models, and serializers |
| `tables/services/graph_bulk_save_service/saveables.py` | Saveable wrapper classes for deferred node and edge writes; temp_id resolution |
| `tables/models/graph_models.py` | All graph model definitions (`CrewNode`, `PythonNode`, `Edge`, `ConditionalEdge`, etc.) |
| `tables/exceptions.py` | `BulkSaveValidationError` — raised by the service, caught in the view |
| `tables/swagger_schemas/graph_bulk_save_schema.py` | Swagger/OpenAPI schema definition for the endpoint |
| `tests/api_tests/bulk_save_test/test_bulk_save.py` | Integration tests covering create, update, delete, temp_id edge wiring, and error cases |
