# Secret Usage

Deleting a secret always succeeds and breaks things silently — every FK is
`on_delete=SET_NULL` and the `PythonCode.secrets` M2M rows just disappear. Nothing raises;
a flow simply stops having a credential. Secret Usage exists so the UI can tell the user
what they are about to break, because the database will not.

Two surfaces, backed by one registry:

- `usage_count` on every `/api/secrets/` row — "how many things reference this?"
- `GET /api/secrets/{id}/usage/` — "*which* things, exactly?"

Endpoint shapes are in [secrets_endpoints.md](secrets_endpoints.md).

---

## 1. The source registry

`tables/services/secrets/usage_sources.py` — `USAGE_SOURCES`, twelve `UsageSource` entries.
One dataclass describes every place the platform can reference a `Secret`, so adding a
reference site is a registry entry rather than a new query.

| Model | Category | Shape | `code_field` |
|---|---|---|---|
| `LLMConfig` | `llm_configs` | named | — |
| `EmbeddingConfig` | `llm_configs` | named | — |
| `RealtimeConfig` | `llm_configs` | named | — |
| `RealtimeTranscriptionConfig` | `llm_configs` | named | — |
| `McpTool` | `tools` | named | — |
| `PythonCodeTool` | `tools` | named | `python_code` |
| `TelegramTriggerNode` | `flows` | node | — (FK site) |
| `PythonNode` | `flows` | node | `python_code` |
| `WebhookTriggerNode` | `flows` | node | `python_code` |
| `ClassificationDecisionTableNode` | `flows` | node | `pre_python_code` |
| `ClassificationDecisionTableNode` | `flows` | node | `post_python_code` |
| `ConditionalEdge` | `flows` | edge | `python_code` |

The six declaration sites are generated from `PYTHON_CODE_SITES` via
`_from_python_code_site`, **the same tuple the declaration validator walks**. That sharing is
deliberate: the two features cannot drift on which code sites exist. The risk is asymmetric
— a site missed by the usage sources is a wrong number on a dashboard, while a site missed by
the validator is a hole in the allow-list.

`org_path` is how each source reaches the org (`org_id`, `graph__org_id`, or `None` for
hybrid resources like `PythonCodeTool` that must be scoped with `org_visible_queryset`
because built-ins carry `org=NULL` and an `org_id` filter would hide them).

---

## 2. Counting: `usage_count`

`SecretUsageService.counts(org_id=, secret_ids=None)` returns `{secret_id: count}` in **one
combined query**:

```python
first, *rest = [source.count_pairs(org_id=..., secret_ids=...) for source in USAGE_SOURCES]
for secret_id, _ in first.union(*rest):
    counts[secret_id] += 1
```

Each source projects `(secret_id, resource_key)`. `UNION` — not `UNION ALL` — is already
`DISTINCT`, and each key embeds its category, so the combined result set **is** the set of
distinct (secret, resource) pairs. There is nothing left to dedupe in Python and nothing
fetched but the pairs.

### 2.1 The unit of counting is the resource, and for flows that means the flow

`_key_expression()` produces:

- flows → `flows:<graph_id>` — **the graph, not the node**
- everything else → `<category>:<name>`

So a secret used by three different nodes in one flow counts as **1**, and a decision table
declaring it in both its pre and post blocks also counts as **1**.

That is intentional: the count answers *"how many things break if I delete this?"*, and a
flow is the thing a user recognises. **It is not a node count, and it will not equal the
number of node entries in the detail payload.** The Swagger description says so, because it
is the most likely thing for a frontend to get wrong.

### 2.2 Scoping, and why there are two entry points

`counts()` takes an optional `secret_ids`:

- `None` → every secret in the org. One query to look them up, then the union. This is what
  the **list** endpoint wants.
- explicit → skips the lookup entirely (a caller holding the ids has nothing to look up) and
  narrows the union's `IN` list. **2 queries → 1.**

`count_for(secret=)` is the single-secret entry point. It takes the resolved `Secret` rather
than an id so the org comes from `secret.org_id` — it cannot be called with a mismatched
secret/org pair:

```python
def count_for(self, *, secret: Secret) -> int:
    return self.counts(org_id=secret.org_id, secret_ids={secret.pk})[secret.pk]
```

There is no `if len(ids) == 1` branch anywhere. One secret and five hundred take the same
code path with a different argument.

### 2.3 How the two endpoints choose

Driven by DRF's `many=True`, not by a view inspecting `self.action`:

```python
class SecretUsageCountListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        org_id = self.context["view"].get_active_org_id()
        self.context["usage_counts"] = SimpleLazyObject(
            lambda: secret_usage_service.counts(org_id=org_id)
        )
        return super().to_representation(data)
```

`SecretSerializer.Meta.list_serializer_class` points at it, so it exists **only** when the
serializer is instantiated with `many=True`. Then:

```python
def get_usage_count(self, secret) -> int:
    counts = self.context.get("usage_counts")
    if counts is not None:
        return counts[secret.pk]
    return secret_usage_service.count_for(secret=secret)
```

A list gets one prepared map; retrieve and create never go through the list serializer, so
there is no map and they count their own secret in a single query. This works because
`ListSerializer.__init__` calls `child.bind(...)`, making the child's `.context` and the list
serializer's `.context` **the same dict**.

`SimpleLazyObject` keeps an empty page from paying for a query nothing will read. The load-
bearing test is `test_the_usage_sweep_runs_exactly_once_per_request`: `get_usage_count` is a
`SerializerMethodField` and runs per row, so if the memoisation broke it would be one union
per secret instead of one per request.

The map is indexed directly rather than `.get(pk, 0)` — `counts()` seeds every id it was
given, so a missing key means the service and the queryset disagree, and a `KeyError` says so
instead of rendering it as "unused".

---

## 3. The detail payload

`summary(secret=)` returns:

```json
{
  "total": 3,
  "categories": [
    { "key": "flows", "items": [ { "id": 12, "name": "Payments flow", "nodes": [...] } ] },
    { "key": "tools", "items": [ { "name": "Stripe refund" } ] },
    { "key": "llm_configs", "items": [ { "name": "gpt-4o prod" } ] }
  ]
}
```

Categories are emitted in the fixed `CATEGORY_ORDER` (`flows`, `tools`, `llm_configs`) and a
category is present only when it has items, so an unused secret returns
`{"total": 0, "categories": []}` and the frontend never renders an empty group.

`total` is the number of items across categories — consistent with `usage_count`.

### 3.1 Three queries, not twelve

`_collect` groups sources by `detail_shape` and unions each group:

| Shape | Sources | Columns |
|---|---|---|
| named | 6 | `(secret_id, category, name)` |
| node | 5 | `(secret_id, node_type, graph_id, graph_name, node_name, code_field)` |
| edge | 1 | `(secret_id, node_type, graph_id, graph_name, source_node_id, edge_id, code_field)` |

Sources within a shape already share a column list, so each group unions as-is — no NULL
padding, which is why this beats one twelve-branch union. Per-source constants
(`node_type`, `code_field`) are projected as columns so the assembler can tell which source a
row came from.

A matching conditional edge adds one more pass: `ConditionalEdge` has no name of its own and
borrows the identity of the node it branches off, so `resolve_node_names` resolves those in
one batched call.

> **`Cast(..., output_field=TextField())` on every name column is required, not cosmetic.**
> `custom_name` is `TextField` on `LLMConfig`/`EmbeddingConfig` but `CharField(250)` on the
> two Realtime configs, and `name` is `TextField` on `PythonCodeTool` but `CharField` on
> `McpTool`. An uncast union raises `FieldError: Expression contains mixed types`.

### 3.2 Ordering is explicit because `UNION` has none

SQL guarantees no row order from a `UNION`, so `_flow_items` and `_named_items` sort
explicitly — flows by `(name, id)`, nodes by `(name, node_type, code_field)`, named items by
name. Without this, two identical calls could return differently-ordered payloads.
`TestSummaryIsDeterministic` covers it.

### 3.3 `code_field`: which block uses the secret

Every flow node carries `code_field`, so the frontend never branches on node type to know
whether to look for it:

| Value | Meaning |
|---|---|
| `python_code` | the node's single code block (python, webhook-trigger, edge) |
| `pre_python_code` / `post_python_code` | a classification decision table's two independent declarations |
| `null` | an FK site — `telegram-trigger` references the secret by foreign key and declares nothing in code |

A decision table declares its pre and post blocks **independently**, so such a node appears
**once per declaring block** and the two entries share a name:

```json
"nodes": [
  { "name": "classify", "node_type": "classification-decision-table", "code_field": "post_python_code" },
  { "name": "classify", "node_type": "classification-decision-table", "code_field": "pre_python_code" }
]
```

`code_field` is part of the node's identity in `_flow_items`, not decoration — it is what
stops those two rows from deduping into one entry that cannot say which block is involved.
The count is unaffected (§2.1): still one flow, still `total: 1`.

The block is deliberately **not** encoded into `node_type` (e.g.
`classification-decision-table:pre`). That string is a wire contract mapped to the frontend's
`NodeType` enum, and splitting it would break icon and label lookup.

---

## 4. Usage is *declaration*, not mention

For code sites, a secret is "used" when it is in `PythonCode.secrets` — the allow-list — not
when the code happens to mention its name. A node whose code calls `get_secret("K")` without
declaring `K` is **not** reported as a user of `K`; it is a node that will fail the allow-list
gate at session start.

This matters for deletion safety: the question is "what is authorised to read this", and that
is exactly what the declaration records.

---

## 5. Graph versioning

Version snapshots are built through the **import/export** serializers, which deliberately
exclude every `Secret` reference (`python_tools.py`: `exclude = ["id", "secrets"]`). Saving
and restoring a version therefore used to wipe every declaration on the graph — and with the
allow-list enforcing at session start, a restored flow came back refusing to run.

`GraphVersioningManager` now records the declarations itself, in a `secret_declarations`
snapshot key, and re-links them on both `restore` and `create-graph`.

Four decisions worth knowing:

- **Names, not ids.** Rotation is delete + recreate (`Secret.value` is `editable=False`, no
  update endpoint), so an id would dangle on every rotation while a name survives it.
- **Import/export was left alone.** Its exclusion is correct — Secret PKs are meaningless in
  another org — and `tests/import_export_tests/test_secret_export_exclusion.py` locks it in.
  Versioning is same-graph, same-org, in-place, so it gets its own snapshot key instead.
- **Correlated through `node_mapper`.** The restore wipes and recreates nodes with fresh ids,
  so old snapshot ids mean nothing without remapping. (`BaseNode.node_name` has no unique
  constraint, so names are not a usable key here; node ids come from one shared sequence, so
  they are.)
- **Fail-closed.** A secret deleted since the snapshot, a node dropped by dependency
  filtering, or an ambiguous conditional edge yields a `secret_declaration_dropped` warning
  in the response's existing `warnings` list and **no link** — never a guess. Under-declaring
  costs a precise `UndeclaredSecretError` at session start; over-declaring would authorise a
  node for a credential nobody granted it.

Snapshots saved before this existed have no `secret_declarations` key and restore exactly as
they did, with nothing to re-link.

---

## 6. Adding a source

1. Append a `UsageSource` to `USAGE_SOURCES` with `model`, `secret_path`, `category`,
   `org_path`, `name_field`, and — for flow nodes — `node_type` and `code_field`.
   A declaration site should instead be added to `PYTHON_CODE_SITES`, which generates its
   source automatically **and** brings the allow-list validator along.
2. Check which `detail_shape` it lands in. If it introduces a fourth column shape you must
   add a projection method, an assembler, and entries in `SHAPE_PROJECTIONS` /
   `HITS_ASSEMBLERS` — otherwise the union will fail on mismatched columns.
3. `Cast(..., output_field=TextField())` any name column (§3.1).
4. Confirm `test_registry_covers_every_declared_source` and `TestDetailShapes` still pass —
   they assert the registry covers every declared site and that each shape's column count is
   consistent.
5. If the new model is a graph child that versioning wipes, teach
   `collect_secret_declarations` / `restore_secret_declarations` about it too.
