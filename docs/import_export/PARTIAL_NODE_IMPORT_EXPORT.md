# Partial Node Import / Export

## Comprehensive Technical Documentation for Developers

This document describes the partial import/export system — how it works, how it differs from full import/export, and how it is extended automatically when new node types are added.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Key Components](#key-components)
3. [How It Works](#how-it-works)
4. [Differences from Full Import/Export](#differences-from-full-importexport)
5. [Organization Scoping & Permissions](#organization-scoping--permissions)
6. [API Endpoints](#api-endpoints)

---

## System Overview

Partial import/export allows a selected subset of nodes from a graph — together with their transitive dependencies — to be exported as a standalone file and later imported into any existing graph. Unlike a full graph export, the graph itself is never included in the output; only the chosen nodes and the entities they depend on travel in the file.

On import, the file's dependencies are created (or reused) in the active organization and committed, but the nodes and edges are **not** written to the target graph. They are returned to the client as unsaved content in the shape of `GET /graphs/{id}/`; the client adds them to the canvas, and the normal flow save persists them. Leaving the flow without saving discards them. Dependencies created by the import stay even when the user discards the nodes.

---

## Key Components

| Component | Purpose |
|---|---|
| `GraphPartialExportService` | Collects and serializes selected nodes and their transitive dependencies |
| `PartialImportService` | Creates a partial-export file's dependencies and returns its nodes and edges unsaved, prepared for an existing graph |
| `PartialImportResult` | Return value of `PartialImportService.import_data()` — the dependency `IDMapper` plus the unsaved `content` |
| `PartialExportResult` | Return value of `GraphPartialExportService.export()` — holds serialized data and any collected errors |
| `NodeRef` | Lightweight struct carrying `entity_type` + `node_id` for a single node to export |
| `LIST_KEY_TO_ENTITY_TYPE` | Maps request field names (e.g. `"task_node_list"`) to `EntityType` values |
| `GraphStrategy.recreate_graph_children()` | Creates nodes and edges inside an existing graph with full ID remapping (rolled back by partial import) |

---

## How It Works

### Partial Export

1. **Resolve node instances** — each `NodeRef` is looked up via its strategy's `get_instance()`. Missing nodes are added to `result.errors` and skipped; the rest continue processing.
2. **Collect dependencies recursively** — for each resolved node, `_collect()` calls `strategy.extract_dependencies_from_instance()` and recurses into every dependency. `EntityType.GRAPH` is explicitly excluded so the parent graph is never pulled into the output.
3. **Include requested edges** — `Edge` records for the provided IDs are fetched and added to the collected set. Missing edge IDs are recorded as errors.
4. **Serialize** — every collected instance is serialized using its strategy's `export_entity()`. Edges use `EdgeImportSerializer` directly.

Errors are **collected, not raised**. Callers should check `result.has_errors` before using `result.data`. A non-empty `result.errors` does not necessarily mean the export is unusable — it may only mean some specific nodes or edges were missing.

The output is a plain dict whose top-level keys are `EntityType` string values (e.g. `"TaskNode"`, `"LLMConfig"`) plus the special key `"edge_list"`.

### Partial Import

1. **Collect nodes** — all node entity types present in the export data are gathered into a flat list. Each node dict is tagged with a `"node_type"` key so `GraphStrategy._create_nodes()` can dispatch to the correct strategy.
2. **Import non-node dependencies** — entity types that are not nodes and not `GRAPH` are processed in `DEPENDENCY_ORDER`. For each entity, `find_existing()` is called first (scoped to the active organization):
   - If a match is found in the active org it is reused (`was_created=False`) and the old ID is mapped to the existing entity's ID.
   - If no match is found, `import_entity()` creates a new instance (`was_created=True`) stamped with the active organization.
   - Before each genuinely-new create, CREATE permission is required on the dependency's resource type (see [Organization Scoping & Permissions](#organization-scoping--permissions)).
3. **Build the nodes and edges, then roll them back** — inside a nested `transaction.atomic()` (a savepoint), `GraphStrategy.recreate_graph_children()` is called with the target graph, the collected node list, and the edge list. Internally it:
   - Creates all nodes, numbered from the target graph's node-number counter.
   - Creates edges with node IDs remapped via the local `IDMapper`.
   - Remaps `next_node_id` references in decision tables and classification decision tables; a reference to a node outside the file becomes `null`.

   The new nodes, and the edges whose two ends are both new nodes, are then serialized with the same per-type serializers `GraphSerializer` uses for `GET /graphs/{id}/`, and the savepoint is rolled back. The target graph is left exactly as it was: no nodes, edges, node-number counter change, `save_version` change or last edit. Creating and rolling back reuses every node strategy's validation and normalization and the GET-graph shape without persisting anything; do not replace it with an in-memory conversion. Signal work that a node save defers with `transaction.on_commit` (webhook re-registration, schedule events) is discarded with the savepoint. One side effect does escape: saving a `TelegramTriggerNode` immediately re-pushes the tunnel configs to the `webhook` service. That push carries no node data and is idempotent. It is how Telegram node saves already behave, and partial import does not change it.
4. **Return `PartialImportResult`** — `id_mapper` maps the file's dependency ids to the rows used in the active org (for `id_mapper.get_detailed_summary()`), and `content` holds the unsaved nodes and edges.

The whole operation runs inside one outer `transaction.atomic()` block — a failed import leaves no partial data in the database, dependencies included.

---

## Differences from Full Import/Export

| Aspect | Full export / import | Partial export / import |
|---|---|---|
| Scope | Entire entity with all dependencies | Selected nodes with their dependencies |
| Graph included in file | Yes | No |
| Target on import | New entity created | Nothing written to the graph; nodes and edges returned unsaved for the client to save |
| `ImportSettings` (preserve_uuids, replace_existing, import_labels) | Supported | Not applicable |
| Version conversion | Applied on import | Not applied (no `version` field in output) |
| Labels | Exported and optionally imported | Not exported |

---

## Organization Scoping & Permissions

Partial import/export are actions on the `Graph` viewset and run under the same RBAC layers as every other org-scoped endpoint.

**Active organization.** The active org is resolved from the `X-Organization-Id` header (`OrgContextService`). The target graph is fetched through the org-scoped queryset, so a graph in another org returns 404. Imported **dependencies** (Crew, Agent, LLM/embedding/realtime configs, tools) are created stamped with the active org; `find_existing()` reuse is scoped to the active org, so a dependency id in the file that matches another org's row is not reused — a fresh row is created in the active org. Nodes carry no org column of their own; they are prepared against the target graph, and inherit its org once the user saves the flow.

**View-level verb gate (`HasOrgPermission`).**

| Action | Required permission |
|---|---|
| `partial-export` | `FLOWS` · `EXPORT` |
| `partial-import` | `FLOWS` · `UPDATE` (it prepares content for an existing graph and creates dependencies) |

**Per-dependency create enforcement.** Passing the view gate is not sufficient to create the dependencies an import pulls in. For every genuinely-new dependency (a `find_existing` miss), the caller must have `CREATE` on that dependency's resource type, mapped via `ENTITY_RESOURCE_MAP`:

| Dependency | Resource type |
|---|---|
| Crew | `PROJECTS` |
| Agent | `AGENTS` |
| LLM / embedding / realtime configs & models | `LLM_CONFIGS` |
| Python code tool, MCP tool | `TOOLS` |

Missing permissions are collected across the whole file and raised once as a single `403 PermissionDenied` (`"Missing CREATE permission on: <resources>. No changes were made."`). Reused (already-existing) dependencies need no create permission. Superadmins bypass both the verb gate and the per-dependency checks.

**Secret markers.** A new LLM or embedding config whose `extra_headers` carry an `epicstaff_secret(<name>)` marker also needs `secrets:USE`, because the marker makes runs send that secret. Without it the import is refused with a `400` whose `message` names `extra_headers`, and nothing is written. A reused config is never written, so it needs nothing.

**Trigger nodes.** A file holding a webhook, Telegram or schedule trigger node also needs `FLOWS` · `USE`; without it the whole file is refused with `403 flow_with_trigger_nodes_requires_use_permission` before anything is written.

**Atomicity.** The whole import runs in one `transaction.atomic()` block; a permission denial (or any error) rolls back every insert, so a rejected import leaves no partial data.

This mirrors the enforcement applied to full graph/agent/crew import.

---

## API Endpoints

Both operations are exposed on the `Graph` viewset.

### `POST /graphs/{id}/partial-export`

Exports selected nodes from graph `{id}`.

**Request body** (JSON):

```json
{
  "task_node_list": [5, 7],
  "python_node_list": [3],
  "edge_list": [12]
}
```

Supported list keys: `start_node_list`, `python_node_list`, `audio_transcription_node_list`, `file_extractor_node_list`, `telegram_trigger_node_list`, `webhook_trigger_node_list`, `decision_table_node_list`, `classification_decision_table_node_list`, `subgraph_node_list`, `end_node`, `graph_note_list`, `schedule_trigger_node_list`, `agent_node_list`, `task_node_list`.

The view converts these keys to `NodeRef` objects using `LIST_KEY_TO_ENTITY_TYPE` defined in `services/partial_export_service.py`, then calls `GraphPartialExportService.export()`.

**Response**: a downloadable JSON file containing the serialized nodes and their dependencies.

### `POST /graphs/{id}/partial-import`

Prepares the nodes of a partial-export file for pasting into graph `{id}`. Dependencies are created and committed; nodes and edges are not saved.

**Request body**: multipart/form-data upload of the JSON file produced by `partial-export`.

**Response**: `200` with

```json
{
  "content": {
    "python_node_list": [
      {"id": 901, "node_name": "Pasted python", "node_number": 4, "graph": 12,
       "python_code": {"id": 77, "code": "def main(): ...", "entrypoint": "main"}}
    ],
    "decision_table_node_list": [],
    "edge_list": [{"id": 55, "start_node_id": 900, "end_node_id": 901, "graph": 12}]
  },
  "summary": {"LLMConfig": {"total": 1, "created": {"count": 1, "items": []}, "reused": {"count": 0, "items": []}}}
}
```

(Abridged: every node and edge carries all the fields `GET /graphs/{id}/` returns.)

`content` has every node-list key of `GraphSerializer` plus `edge_list` (`[]` when empty), in the `GET /graphs/{id}/` shape. Its ids — node ids, edge ids and nested ids such as `python_code.id`, agent-node task ids or classification-decision-table prompt ids — were rolled back and never exist in the database: the client must treat every node, edge and nested row as new. `node_number`, `created_by`, `last_edited_by`, `last_edited_at`, `created_at`, `content_hash` and every id in `content` are provisional values from those rolled-back rows; the flow save assigns the real ones. Edge ends and decision-table `next_node_id` references point at node ids inside `content`. `summary` is the dependency summary built from the `IDMapper`.

Returns `403` if the caller lacks `FLOWS.UPDATE` on the graph, lacks `CREATE` on any resource type an imported dependency would create, or lacks `FLOWS.USE` for a file with trigger nodes (see [Organization Scoping & Permissions](#organization-scoping--permissions)); nothing is written in that case. A graph in another organization returns `404`.

---

> **Note:** Partial import/export discovers nodes through the same strategy registry and `NODE_RELATIONS` map used by full graph export. Adding a new node type automatically makes it available for partial export/import once its strategy is registered in `apps.py` and its relation is added to `NODE_RELATIONS` in `strategies/node_handlers.py`. No changes to `GraphPartialExportService` or `PartialImportService` are needed.
