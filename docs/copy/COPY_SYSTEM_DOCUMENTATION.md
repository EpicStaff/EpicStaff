# Copy System Documentation

## Comprehensive Technical Documentation for Developers

This document covers the architecture and workflows of the copy system, and explains how to extend it with new entities or graph node types.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Key Components](#key-components)
3. [How It Works](#how-it-works)
4. [Copyable Entities](#copyable-entities)
5. [Adding a New Top-Level Entity](#adding-a-new-top-level-entity)
6. [Adding a New Node to Graph Copy](#adding-a-new-node-to-graph-copy)
7. [Helpers Reference](#helpers-reference)

---

## System Overview

The copy system duplicates entities within the application. Each copyable entity has its own dedicated service class under `src/django_app/tables/services/copy_services/`. All copy operations are triggered through a `copy` action on the entity's ViewSet and are wrapped in `transaction.atomic()` — a failed copy leaves no partial data in the database.

---

## Key Components

| Component | Purpose |
|---|---|
| `BaseCopyService` | Abstract base class defining the `copy(entity, name=None)` interface for all copy services |
| Copy service classes | Entity-specific logic for duplicating each model and its relationships (inherit `BaseCopyService`) |
| `CopyActionMixin` | ViewSet mixin that provides the standard `copy` action, configured via `copy_service_class` and `copy_serializer_class` |
| `NODE_COPY_HANDLERS` | Registry mapping each `NodeType` to a handler function used during graph copy |
| `helpers.py` | Shared utilities: `copy_python_code`, `get_base_node_fields` |
| `ensure_unique_identifier` | Generates a unique name by appending `(2)`, `(3)`, … when a name conflict exists |

---

## How It Works

1. **Request**: A `POST /api/{entity}/{id}/copy/` request is received with an optional `name` field in the body.
2. **Transaction**: The ViewSet action opens `transaction.atomic()`.
3. **Service call**: The appropriate copy service is instantiated and its `copy(instance, name)` method is called.
4. **Name resolution**: `ensure_unique_identifier` checks existing names and appends a numeric suffix if needed.
5. **Entity creation**: A new model instance is created with all scalar fields copied from the original.
6. **Relationship handling**: Relationships are either re-linked (shared references) or fully duplicated depending on the entity — see [Copyable Entities](#copyable-entities).
7. **Post-processing** (graphs only): Internal node ID references are remapped using `node_id_map`.
8. **Response**: The newly created entity is serialized and returned as **201 CREATED**.

---

## Copyable Entities

### Agent — `AgentCopyService`

- All scalar config fields are duplicated.
- Tool relationships (`AgentConfiguredTools`, `AgentPythonCodeTools`, `AgentMcpTools`, etc.) are **re-linked** to the same tool objects — tools are not cloned.
- `RealtimeAgent` is fully duplicated if present; the absence is handled silently.

### Crew — `CrewCopyService`

- All scalar config fields are duplicated.
- Agents are **re-linked** (not cloned).
- Tasks are **fully cloned**. A `task_id_map` (`old_id → new_task`) is built in the first pass.
- `TaskContext` dependencies are remapped to the new tasks in a second pass to avoid dangling references.

### Graph — `GraphCopyService`

- All scalar fields are duplicated.
- Every node is cloned via `NODE_COPY_HANDLERS` (see below). A `node_id_map` (`old_id → new_id`) is built during this step.
- `Edge` and `ConditionalEdge` records are cloned with `start_node_id`/`end_node_id`/`source_node_id` remapped through `node_id_map`.
- Each `ConditionalEdge` gets a **new** `PythonCode` object.
- After all nodes and edges are created, two post-processing passes remap any remaining node ID references:
  - `_remap_decision_table_references` — fixes `default_next_node_id`, `next_error_node_id`, and per-group `next_node_id` on `DecisionTableNode`.
  - `_remap_metadata_node_ids` — fixes node IDs embedded in the graph `metadata` JSON.

### PythonCodeTool — `PythonCodeToolCopyService`

- A **new** `PythonCode` object is always created (not shared).
- `PythonCodeToolConfigField` entries are fully cloned.
- Built-in tools cannot be copied and raise `ValueError`.

### McpTool — `McpToolCopyService`

- All scalar fields are duplicated. No nested objects.

---

## Adding a New Top-Level Entity

1. **Create a service** in `src/django_app/tables/services/copy_services/`, inheriting from `BaseCopyService`:

   ```python
   # my_entity_copy_service.py
   from tables.import_export.utils import ensure_unique_identifier
   from tables.models import MyEntity
   from tables.services.copy_services.base_copy_service import BaseCopyService

   class MyEntityCopyService(BaseCopyService):
       """Copy service for MyEntity."""

       def copy(self, entity: MyEntity, name: str | None = None) -> MyEntity:
           existing_names = MyEntity.objects.values_list("name", flat=True)
           new_name = ensure_unique_identifier(
               base_name=name if name else entity.name,
               existing_names=existing_names,
           )
           return MyEntity.objects.create(
               name=new_name,
               # copy other fields here
           )
   ```

2. **Add `CopyActionMixin` to the ViewSet** in `model_view_sets.py`:

   ```python
   class MyEntityViewSet(CopyActionMixin, ModelViewSet):
       copy_service_class = MyEntityCopyService
       copy_serializer_class = MyEntitySerializer
       # No need to write a copy method — CopyActionMixin provides it.
   ```

---

## Adding a New Node to Graph Copy

The graph copy service dispatches node creation through `NODE_COPY_HANDLERS` — a dictionary in `node_copy_handlers.py` that maps each `NodeType` to a `(relation_name, handler_function)` tuple.

### Steps

1. **Write a handler function** in `node_copy_handlers.py`:

   ```python
   def copy_my_new_node(graph: Graph, node: MyNewNode) -> MyNewNode:
       return MyNewNode.objects.create(
           graph=graph,
           **get_base_node_fields(node),   # copies input_map, node_name, output_variable_path, metadata
           my_extra_field=node.my_extra_field,
       )
   ```

   - If the node owns a `PythonCode` object, duplicate it with `copy_python_code(node.python_code)`.
   - If the node has nested child objects (like `TelegramTriggerNodeField`), iterate and clone them inside the handler.
   - If the node holds a **reference** to another entity (like `SubGraphNode → subgraph`), pass the same FK — do not clone the referenced entity.

2. **Register the handler** in `NODE_COPY_HANDLERS`:

   ```python
   NODE_COPY_HANDLERS: dict[NodeType, tuple[str, Callable]] = {
       # ... existing entries ...
       NodeType.MY_NEW_NODE: ("my_new_node_list", copy_my_new_node),
   }
   ```

   - `NodeType.MY_NEW_NODE` must exist in the `NodeType` enum (`tables/import_export/enums.py`).
   - `"my_new_node_list"` is the reverse accessor name on the `Graph` model (the `related_name` of the FK on `MyNewNode`).

3. **Check for post-processing needs**: If the new node stores references to other node IDs (like `DecisionTableNode` does), add remapping logic in `GraphCopyService._remap_decision_table_references` or create a dedicated `_remap_*` method and call it at the end of `GraphCopyService.copy()`.

That's all. The `GraphCopyService` loop picks up the new handler automatically — no changes to `graph_copy_service.py` are needed unless post-processing is required.

---

## Helpers Reference

### `copy_python_code(python_code: PythonCode) -> PythonCode`

Creates and returns a new `PythonCode` instance with all fields duplicated (`code`, `entrypoint`, `libraries`, `global_kwargs`). Use this whenever a node or tool owns a `PythonCode` object to avoid shared mutable state between the original and the copy.

### `get_base_node_fields(node) -> dict`

Returns a dictionary of the shared `BaseNode` fields: `input_map`, `node_name`, `output_variable_path`, `metadata`. Pass `**get_base_node_fields(node)` when creating most node types to avoid repeating the same four field assignments in every handler.
