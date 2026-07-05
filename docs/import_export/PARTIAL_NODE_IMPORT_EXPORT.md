# Partial Node Import / Export

## Comprehensive Technical Documentation for Developers

This document describes the partial import/export system — how it works, how it differs from full import/export, and how it is extended automatically when new node types are added.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Key Components](#key-components)
3. [How It Works](#how-it-works)
4. [Differences from Full Import/Export](#differences-from-full-importexport)
5. [API Endpoints](#api-endpoints)

---

## System Overview

Partial import/export allows a selected subset of nodes from a graph — together with their transitive dependencies — to be exported as a standalone file and later imported into any existing graph. Unlike a full graph export, the graph itself is never included in the output; only the chosen nodes and the entities they depend on travel in the file.

On import, nodes are appended to the target graph and all IDs are remapped. No new graph is created.

---

## Key Components

| Component | Purpose |
|---|---|
| `GraphPartialExportService` | Collects and serializes selected nodes and their transitive dependencies |
| `PartialImportService` | Imports a partial-export file into an existing graph |
| `PartialExportResult` | Return value of `GraphPartialExportService.export()` — holds serialized data and any collected errors |
| `NodeRef` | Lightweight struct carrying `entity_type` + `node_id` for a single node to export |
| `LIST_KEY_TO_ENTITY_TYPE` | Maps request field names (e.g. `"crew_node_list"`) to `EntityType` values |
| `GraphStrategy.recreate_graph_children()` | Creates nodes and edges inside an existing graph with full ID remapping |

---

## How It Works

### Partial Export

1. **Resolve node instances** — each `NodeRef` is looked up via its strategy's `get_instance()`. Missing nodes are added to `result.errors` and skipped; the rest continue processing.
2. **Collect dependencies recursively** — for each resolved node, `_collect()` calls `strategy.extract_dependencies_from_instance()` and recurses into every dependency. `EntityType.GRAPH` is explicitly excluded so the parent graph is never pulled into the output.
3. **Include requested edges** — `Edge` records for the provided IDs are fetched and added to the collected set. Missing edge IDs are recorded as errors.
4. **Serialize** — every collected instance is serialized using its strategy's `export_entity()`. Edges use `EdgeImportSerializer` directly.

Errors are **collected, not raised**. Callers should check `result.has_errors` before using `result.data`. A non-empty `result.errors` does not necessarily mean the export is unusable — it may only mean some specific nodes or edges were missing.

The output is a plain dict whose top-level keys are `EntityType` string values (e.g. `"CrewNode"`, `"LLMConfig"`) plus the special key `"edge_list"`.

### Partial Import

1. **Collect nodes** — all node entity types present in the export data are gathered into a flat list. Each node dict is tagged with a `"node_type"` key so `GraphStrategy._create_nodes()` can dispatch to the correct strategy.
2. **Import non-node dependencies** — entity types that are not nodes and not `GRAPH` are processed in `DEPENDENCY_ORDER`. For each entity, `find_existing()` is called first:
   - If a match is found it is reused (`was_created=False`) and the old ID is mapped to the existing entity's ID.
   - If no match is found, `import_entity()` creates a new instance (`was_created=True`).
3. **Recreate graph children** — `GraphStrategy.recreate_graph_children()` is called with the target graph, the collected node list, and the edge lists. Internally it:
   - Creates all nodes, replacing each `node_name` suffix with the next available counter for the target graph to avoid name collisions.
   - Creates edges with node IDs remapped via the local `IDMapper`.
   - Remaps `next_node_id` references in decision tables and classification decision tables.
   - Updates node ID references embedded in the graph's `metadata` JSON field.
4. **Return `IDMapper`** — the caller receives a full mapping of old → new IDs, usable for building a creation summary via `id_mapper.get_detailed_summary()`.

The entire operation runs inside a single `transaction.atomic()` block — a failed import leaves no partial data in the database.

---

## Differences from Full Import/Export

| Aspect | Full export / import | Partial export / import |
|---|---|---|
| Scope | Entire entity with all dependencies | Selected nodes with their dependencies |
| Graph included in file | Yes | No |
| Target on import | New entity created | Nodes appended to an existing graph |
| `ImportSettings` (preserve_uuids, replace_existing, import_labels) | Supported | Not applicable |
| Version conversion | Applied on import | Not applied (no `version` field in output) |
| Labels | Exported and optionally imported | Not exported |

---

## API Endpoints

Both operations are exposed on the `Graph` viewset.

### `POST /graphs/{id}/partial-export`

Exports selected nodes from graph `{id}`.

**Request body** (JSON):

```json
{
  "crew_node_list": [5, 7],
  "python_node_list": [3],
  "edge_list": [12]
}
```

Supported list keys: `start_node_list`, `crew_node_list`, `python_node_list`, `audio_transcription_node_list`, `file_extractor_node_list`, `telegram_trigger_node_list`, `webhook_trigger_node_list`, `decision_table_node_list`, `classification_decision_table_node_list`, `subgraph_node_list`, `end_node_list`, `graph_note_list`, `code_agent_node_list`, `schedule_trigger_node_list`.

The view converts these keys to `NodeRef` objects using `LIST_KEY_TO_ENTITY_TYPE` defined in `services/partial_export_service.py`, then calls `GraphPartialExportService.export()`.

**Response**: a downloadable JSON file containing the serialized nodes and their dependencies.

### `POST /graphs/{id}/partial-import`

Imports nodes from a partial-export file into graph `{id}`.

**Request body**: multipart/form-data upload of the JSON file produced by `partial-export`.

**Response**: a summary of all entities created or reused during the import, built from the returned `IDMapper`.

---

> **Note:** Partial import/export discovers nodes through the same strategy registry and `NODE_RELATIONS` map used by full graph export. Adding a new node type automatically makes it available for partial export/import once its strategy is registered in `apps.py` and its relation is added to `NODE_RELATIONS` in `strategies/node_handlers.py`. No changes to `GraphPartialExportService` or `PartialImportService` are needed.
