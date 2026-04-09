# Adding a New Node Type to the Bulk Save Service

This document describes every file you need to touch (and which ones you do **not** need to touch) when registering a new node type with the bulk save flow.

---

## Architecture Summary

The bulk save system is driven by `NODE_TYPE_REGISTRY` — a list of `NodeTypeConfig` entries in `registry.py`. Most of the machinery reads from this registry at runtime, so adding a new node type requires only a minimal set of changes.

```
NODE_TYPE_REGISTRY
    ↓ drives
GraphBulkSaveInputSerializer   — auto-injects list fields
DeletedEntitiesSerializer      — auto-injects delete id fields
GraphBulkSaveService (Pass 1)  — iterates configs for validation
GraphBulkSaveService (Pass 2)  — iterates configs for deletions
_collect_payload_temp_ids      — iterates configs for temp_id scan
```

Edges (`edge_list`, `conditional_edge_list`) are **not** in the registry. They have their own validation path in the service. This guide only covers regular node types.

---

## Case 1 — Standard Node (no nested write logic)

Most nodes fall into this category: a flat or shallow serializer, no custom save behaviour needed.

### Step 1 — Add a bulk serializer

File: `tables/serializers/graph_bulk_save_serializers.py`

```python
from tables.serializers.model_serializers import YourNewNodeSerializer

class YourNewNodeBulkSerializer(BulkSaveEntityMixin, YourNewNodeSerializer):
    pass
```

`BulkSaveEntityMixin` injects the optional `id` and wire-only `temp_id` fields automatically. No other changes to this class are needed.

### Step 2 — Register the node type

File: `tables/services/graph_bulk_save_service/registry.py`

Add an import at the top:

```python
from tables.models.graph_models import YourNewNode
```

Add an import for the serializer:

```python
from tables.serializers.graph_bulk_save_serializers import YourNewNodeBulkSerializer
```

Add one entry to `NODE_TYPE_REGISTRY`:

```python
NODE_TYPE_REGISTRY: list[NodeTypeConfig] = [
    # ... existing entries ...
    NodeTypeConfig(
        "your_new_node_list",      # list_key  — key in the request payload
        "your_new_node_ids",       # delete_key — key in deleted{}
        YourNewNode,               # model_class
        YourNewNodeBulkSerializer, # serializer_class
    ),
]
```

No `saveable_factory` argument is needed; the default factory (`DefaultNodeSaveableFactory`) is used automatically.

### Step 3 — Add a Prefetch in GraphViewSet

File: `tables/views/model_view_sets.py`, method `GraphViewSet.get_queryset()`

The graph read serializer returns all node lists. Add a `Prefetch` so the refreshed graph returned after a save includes the new node type:

```python
Prefetch("your_new_node_list", queryset=YourNewNode.objects.all()),
```

The `related_name` on the `graph` FK of your model must match the first argument — by convention `{snake_case_model_name}_list`.

### Step 4 — Update the Swagger schema

File: `tables/swagger_schemas/graph_bulk_save_schema.py`

Add the new list key to the `request_body` properties:

```python
"your_new_node_list": openapi.Schema(type=openapi.TYPE_ARRAY, items=_node_item),
```

Add the new delete key inside the `deleted` schema properties:

```python
"your_new_node_ids": _id_list,
```

---

### What updates automatically (no changes needed)

| Component | Why |
|---|---|
| `GraphBulkSaveInputSerializer` | `get_fields()` injects a list field for every `config.list_key` in the registry |
| `DeletedEntitiesSerializer` | `get_fields()` injects a delete-id field for every `config.delete_key` in the registry |
| Service Pass 1 validation loop | Iterates `NODE_TYPE_REGISTRY`; new config is picked up automatically |
| Service deletion loop | Same — new config's `delete_key` is handled without code changes |
| `_collect_payload_temp_ids` | Scans every `config.list_key` in the registry for `temp_id` values |

---

## Case 2 — Node with Nested Write Logic

Use this when your node has related objects that must be created/replaced as part of the same save (like `DecisionTableNode` with `ConditionGroup` / `Condition`).

### Step 1 — Same as Case 1

Create `YourNewNodeBulkSerializer` in `graph_bulk_save_serializers.py`.

### Step 2 — Create a custom Saveable

File: `tables/services/graph_bulk_save_service/saveables.py`

```python
class YourNewNodeSaveable:
    """
    Wraps a validated YourNewNodeBulkSerializer and any extra nested data.

    Defers the actual save so it executes inside the atomic write phase.
    """

    def __init__(self, serializer, nested_data, instance=None):
        self._serializer = serializer
        self._nested_data = nested_data
        self._instance = instance

    def save(self):
        s = self._serializer
        validated = dict(s.validated_data)
        _clean_for_write(validated)

        node = (
            s.create(validated)
            if s.instance is None
            else s.update(s.instance, validated)
        )

        # Replace nested relations (delete old, bulk-create new).
        if self._instance is not None:
            RelatedModel.objects.filter(your_new_node=node).delete()

        if self._nested_data:
            # bulk-create the nested objects here
            pass

        return node
```

`_clean_for_write` strips wire-only fields (e.g. `temp_id`) before the ORM write. Always call it on `validated_data`.

### Step 3 — Create a custom SaveableFactory

File: `tables/services/graph_bulk_save_service/factories/your_new_node.py`

```python
from tables.services.graph_bulk_save_service.factories.base import NodeSaveableFactory
from tables.services.graph_bulk_save_service.saveables import YourNewNodeSaveable

class YourNewNodeSaveableFactory(NodeSaveableFactory):
    def preprocess_data(self, data: dict, payload_temp_ids: set) -> tuple[dict, dict]:
        # Pop nested fields the serializer must not see.
        nested = data.pop("your_nested_field", None)
        return data, {"your_nested_field": nested}

    def build(self, serializer, extra: dict, instance=None):
        return YourNewNodeSaveable(
            serializer, extra.get("your_nested_field"), instance
        )
```

Re-export from `tables/services/graph_bulk_save_service/factories/__init__.py`:

```python
from .your_new_node import YourNewNodeSaveableFactory
```

Create a singleton in `registry.py` (factories are stateless):

```python
_YOUR_NEW_FACTORY = YourNewNodeSaveableFactory()
```

### Step 4 — Register with the custom factory

```python
NodeTypeConfig(
    "your_new_node_list",
    "your_new_node_ids",
    YourNewNode,
    YourNewNodeBulkSerializer,
    saveable_factory=_YOUR_NEW_FACTORY,
),
```

### Steps 5 & 6 — Prefetch + Swagger

Same as Case 1 Steps 3 and 4.

---

## Checklist

### Standard node

- [ ] `graph_bulk_save_serializers.py` — add `XxxNodeBulkSerializer(BulkSaveEntityMixin, XxxNodeSerializer)`
- [ ] `registry.py` — add `NodeTypeConfig` entry to `NODE_TYPE_REGISTRY`
- [ ] `model_view_sets.py` — add `Prefetch("xxx_list", ...)` in `GraphViewSet.get_queryset()`
- [ ] `graph_bulk_save_schema.py` — add list key to request body properties and delete key to `deleted` properties

### Node with nested write logic (in addition to the above)

- [ ] `saveables.py` — add `XxxNodeSaveable` class
- [ ] `factories/xxx_node.py` — add `XxxNodeSaveableFactory` class
- [ ] `factories/__init__.py` — re-export the new factory
- [ ] `registry.py` — add factory singleton, pass to `NodeTypeConfig`

---

## Example: adding a hypothetical `CommentNode`

**`graph_bulk_save_serializers.py`**
```python
class CommentNodeBulkSerializer(BulkSaveEntityMixin, CommentNodeSerializer):
    pass
```

**`registry.py`** (import + registry entry)
```python
from tables.models.graph_models import CommentNode
from tables.serializers.graph_bulk_save_serializers import CommentNodeBulkSerializer

# Inside NODE_TYPE_REGISTRY:
NodeTypeConfig(
    "comment_node_list",
    "comment_node_ids",
    CommentNode,
    CommentNodeBulkSerializer,
),
```

**`model_view_sets.py`** (inside `get_queryset` prefetch list)
```python
Prefetch("comment_node_list", queryset=CommentNode.objects.all()),
```

**`graph_bulk_save_schema.py`**
```python
# In request_body properties:
"comment_node_list": openapi.Schema(type=openapi.TYPE_ARRAY, items=_node_item),

# In deleted properties:
"comment_node_ids": _id_list,
```

After these four changes the new node type is fully integrated: it can be created, updated, and deleted through the bulk save endpoint, and errors are reported in the standard `{ "index": N, "errors": ... }` format alongside all other node types.

---

## Key Files Reference

| File | Role |
|---|---|
| `tables/serializers/graph_bulk_save_serializers.py` | Bulk serializer definitions; `BulkSaveEntityMixin` adds `id` and `temp_id` |
| `tables/services/graph_bulk_save_service/registry.py` | `NODE_TYPE_REGISTRY`, `NodeTypeConfig`, factory singletons |
| `tables/services/graph_bulk_save_service/factories/base.py` | `NodeSaveableFactory` ABC, `DefaultNodeSaveableFactory` |
| `tables/services/graph_bulk_save_service/factories/decision_table.py` | `DecisionTableNodeSaveableFactory` |
| `tables/services/graph_bulk_save_service/saveables.py` | `_SerializerSaveable`, `DecisionTableNodeSaveable`, `_NodeSaveable`, `_EdgeSaveable`, `_ConditionalEdgeSaveable` |
| `tables/services/graph_bulk_save_service/service.py` | `GraphBulkSaveService` — two-pass validation and atomic write orchestration |
| `tables/views/model_view_sets.py` | `GraphViewSet.get_queryset()` — prefetch for the read response after save |
| `tables/swagger_schemas/graph_bulk_save_schema.py` | Swagger schema for the `POST /api/graphs/{pk}/save/` endpoint |
