# Secret Usage

Deleting a secret always succeeds and breaks things silently — every FK is
`on_delete=SET_NULL` and the `PythonCode.secrets` M2M rows just disappear. Nothing raises;
a flow simply stops having a credential. Secret Usage exists so the UI can tell the user
what they are about to break, because the database will not.

Two surfaces, backed by one registry:

- `usage_count` on every `/api/secrets/` row — "how many things reference this, and how many
  of them can I actually see?"
- `GET /api/secrets/{id}/usage/` — "*which* things, exactly — limited to what I can see."

Both are **permission-filtered**: a caller only sees the resources they hold READ on. See
§2 and §3.

Endpoint shapes are in [secrets_endpoints.md](secrets_endpoints.md).

---

## 1. The source registry

`tables/services/secrets/usage_sources.py` — `USAGE_SOURCES`, currently **19**
`UsageSource` entries (pinned by `test_registry_covers_every_declared_source` /
`len(USAGE_SOURCES) == 19` — if this table and that count disagree, the count is right and
this table is stale). One dataclass describes every place the platform can reference a
`Secret`, so adding a reference site is a registry entry rather than a new query.

| Model | Category | Shape | `code_field` | `rbac_resource_types` |
|---|---|---|---|---|
| `LLMConfig` | `llm_configs` | named | — | `{llm_configs}` |
| `EmbeddingConfig` | `llm_configs` | named | — | `{llm_configs}` |
| `RealtimeConfig` | `llm_configs` | named | — | `{llm_configs}` |
| `RealtimeTranscriptionConfig` | `llm_configs` | named | — | `{llm_configs}` |
| `OpenAIRealtimeConfig` (`api_key_secret`) | `llm_configs` | named | — | `{llm_configs}` |
| `OpenAIRealtimeConfig` (`transcription_api_key_secret`) | `llm_configs` | named | — | `{llm_configs}` |
| `ElevenLabsRealtimeConfig` | `llm_configs` | named | — | `{llm_configs}` |
| `GeminiRealtimeConfig` | `llm_configs` | named | — | `{llm_configs}` |
| `McpTool` | `tools` | named | — | `{tools}` |
| `TelegramTriggerNode` | `flows` | node | — (FK site) | `{flows}` |
| `TwilioChannel` | `channels` | named | — | `{voice}` |
| `NgrokWebhookConfig` | `channels` | named | — | `{llm_configs}` + conditional `{flows, voice}` |
| `WebhookTriggerAuth` | `channels` | named | — | `{llm_configs}` + conditional `{flows, voice}` |
| `PythonNode` | `flows` | node | `python_code` | `{flows}` |
| `WebhookTriggerNode` | `flows` | node | `python_code` | `{flows}` |
| `ClassificationDecisionTableNode` | `flows` | node | `pre_python_code` | `{flows}` |
| `ClassificationDecisionTableNode` | `flows` | node | `post_python_code` | `{flows}` |
| `ConditionalEdge` | `flows` | edge | `python_code` | `{flows}` |
| `PythonCodeTool` | `tools` | named | `python_code` | `{tools}` |

The six declaration sites are generated from `PYTHON_CODE_SITES` via
`_from_python_code_site`, **the same tuple the declaration validator walks**. That sharing is
deliberate: the two features cannot drift on which code sites exist. The risk is asymmetric
— a site missed by the usage sources is a wrong number on a dashboard, while a site missed by
the validator is a hole in the allow-list.

`org_path` is how each source reaches the org (`org_id`, `graph__org_id`, or `None` for
hybrid resources like `PythonCodeTool` that must be scoped with `org_visible_queryset`
because built-ins carry `org=NULL` and an `org_id` filter would hide them).

---

## 2. Permission-filtered counting: `usage_count`

`usage_count` is `{"readable": int, "hidden": int}`, not a single integer.

### 2.1 Why the count is split in two

Different sources answer to different RBAC resource types, and a secret is typically
referenced from more than one — an `LLMConfig` and a flow, say. A caller may hold
`flows:READ` without holding `llm_configs:READ`, so a single number cannot answer both
questions the UI has to ask: *how much of this can I inspect?* and *how much breaks if I
delete it?*

`readable` and `hidden` partition one distinct-resource count (§2.4) into what the caller can
and cannot see. The split concerns **who is told about which resource**, never how many are
counted: `readable + hidden` is the total number of distinct resources referencing the
secret, identical for every caller in the org.

### 2.2 `UsageSource.rbac_resource_types` — the static case

Every source declares which RBAC resource types grant visibility of it, as a
`frozenset[str]` of `ResourceType` values (`tables/models/rbac_models/rbac_enums.py`):

```python
UsageSource(
    model=LLMConfig,
    ...,
    rbac_resource_types=frozenset({RBAC_LLM_CONFIGS}),
)
```

For 17 of the 19 sources this is the whole story: the caller sees the source if
`readable_types & source.rbac_resource_types` is non-empty, where `readable_types` is every
resource type the caller's `EffectivePermissions` holds READ on
(`SecretUsageService.readable_types`).

### 2.3 `conditional_paths` — the row-level case

Two sources, `NgrokWebhookConfig` and `WebhookTriggerAuth`, need more than a static type set.
Both point at a `WebhookTrigger`, which is reachable three ways:

- its own endpoint, gated `llm_configs:READ` — **unconditional**, since the row is listed
  directly regardless of what references it
- a graph node that references it, gated `flows:READ` — **conditional** on a live node
  actually existing
- a Twilio channel that references it, gated `voice:READ` — same, conditional

Because every one of those back-references is `on_delete=SET_NULL`, an orphaned trigger (its
node deleted, the FK nulled instead of the row cascading) is a real, reachable state — not a
hypothetical. A `flows:READ`-only caller has no route to an orphaned trigger at all, so
treating `flows` as an unconditional grant for these two sources would let the detail payload
(§3) name a resource the caller cannot actually open.

`ConditionalPath.exists(org_id=)` is an `EXISTS` subquery checked per row —
`WebhookTriggerNode`/`TelegramTriggerNode` (`flows`) and `TwilioChannel` (`voice`), each
scoped to the same org and, for the two node models, excluding soft-deleted rows explicitly
(`is_soft_deleted=False` — a related-model `.filter()` does not apply the model's default
manager, so this has to be stated, not inherited).

`UsageSource.readability(readable_types=, org_id=)` returns `READABLE_ALWAYS`,
`READABLE_NEVER`, or — only when a conditional path is what grants visibility — a `Q`
evaluated per row.

### 2.4 One query, one union, one boolean column

`counts()` is one combined query. Each source's `count_pairs()` projects three columns —
`(secret_id, resource_key, is_readable)`:

```python
first, *rest = [
    source.count_pairs(org_id=..., secret_ids=..., readability=source.readability(...))
    for source in USAGE_SOURCES
]
for secret_id, usage_key, is_readable in first.union(*rest):
    (readable_keys if is_readable else hidden_keys)[secret_id].add(usage_key)
```

`is_readable` is `Value(True)`/`Value(False)` whenever `readability()` resolved statically —
no SQL, decided once from the caller's bitmask — and the `Q` wrapped in `ExpressionWrapper`
only when a conditional path is what grants visibility. That is at most the two webhook
sources, and not even those for a caller holding `llm_configs:READ`, since their
unconditional set matches first. Permission-awareness therefore costs nothing in query
count — it is one extra column on a single `UNION`, not an extra pass.

**The tie-break.** Non-flow `usage_key`s are built from a display **name**
(`"<category>:<resource_type>:<name>"`), and names are not guaranteed unique — two ngrok
configs can share a name. If one is visible to the caller and the other is not, that one key
is produced as both readable and hidden. Rule: **a key present in both buckets counts once,
as readable** —

```python
hidden=len(hidden_keys[secret_id] - readable_keys[secret_id])
```

— so `readable + hidden` equals the distinct-key total exactly, never double-counting a
contested key.

### 2.5 The unit of counting is the resource, and for flows that means the flow

`_key_expression()` produces:

- flows → `flows:<graph_id>` — **the graph, not the node**
- everything else → `<category>:<resource_type>:<name>`

So a secret used by three different nodes in one flow counts as **1** in whichever
bucket the caller's flow access puts it in.

### 2.6 Scoping, and why there are two entry points

`counts(org_id=, effective=, secret_ids=None)`:

- `secret_ids=None` → every secret in the org. One query to look them up, then the union.
  This is what the **list** endpoint wants.
- explicit → skips the lookup entirely and narrows the union's `IN` list. **2 queries → 1.**

`count_for(secret=, effective=)` is the single-secret entry point:

```python
def count_for(self, *, secret: Secret, effective) -> UsageCounts:
    return self.counts(
        org_id=secret.org_id, effective=effective, secret_ids={secret.pk}
    )[secret.pk]
```

`UsageCounts` is a frozen dataclass — `readable: int`, `hidden: int`. There is no
`if len(ids) == 1` branch anywhere. One secret and five hundred take the same code path with
a different argument.

`effective` is a **required** keyword everywhere, deliberately with no permissive default —
a default granting everything would let a forgotten call site silently return unfiltered
counts while passing every static check.

### 2.7 How the two endpoints choose

Driven by DRF's `many=True`, not by a view inspecting `self.action`:

```python
class SecretUsageCountListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        org_id = self.context["view"].get_active_org_id()
        effective = _effective_for(context=self.context)
        self.context["usage_counts"] = SimpleLazyObject(
            lambda: secret_usage_service.counts(org_id=org_id, effective=effective)
        )
        return super().to_representation(data)
```

`SecretSerializer.Meta.list_serializer_class` points at it, so it exists **only** when the
serializer is instantiated with `many=True`. Then:

```python
def get_usage_count(self, secret) -> dict:
    counts = self.context.get("usage_counts")
    if counts is None:
        counts = {
            secret.pk: secret_usage_service.count_for(
                secret=secret, effective=_effective_for(context=self.context)
            )
        }
    return {"readable": counts[secret.pk].readable, "hidden": counts[secret.pk].hidden}
```

A list gets one prepared map; retrieve and create never go through the list serializer, so
there is no map and they resolve permissions and count their own secret directly. This works
because `ListSerializer.__init__` calls `child.bind(...)`, making the child's `.context` and
the list serializer's `.context` **the same dict**.

`_effective_for` (`tables/serializers/model_serializers/secret_serializers.py`) resolves the
requesting user's `EffectivePermissions` in the active org via `PermissionResolver` —
`HasOrgPermission` does not stash this on the request, so the serializer resolves it itself,
the same pattern `SecretReferenceGuard` uses
([DEV_rbac_backend_guide.md](../rbac/DEV_rbac_backend_guide.md) §5.6).

`SimpleLazyObject` keeps an empty page from paying for a query nothing will read. The load-
bearing test is `test_the_usage_sweep_runs_exactly_once_per_request`: `get_usage_count` is a
`SerializerMethodField` and runs per row, so if the memoisation broke it would be one union
per secret instead of one per request.

The map is indexed directly rather than `.get(pk, ...)` — `counts()` seeds every id it was
given, so a missing key means the service and the queryset disagree, and a `KeyError` says so
instead of rendering it as "unused".

---

## 3. The detail payload

`summary(secret=, effective=)` returns:

```json
{
  "readable_total": 3,
  "hidden_total": 1,
  "categories": [
    { "key": "flows", "items": [ { "id": 12, "name": "Payments flow", "nodes": [...] } ] },
    { "key": "tools", "items": [ { "name": "Stripe refund", "type": "mcp_tool" } ] },
    { "key": "llm_configs", "items": [ { "name": "gpt-4o prod", "type": "llm_config" } ] }
  ]
}
```

Categories are emitted in the fixed `CATEGORY_ORDER` (`flows`, `tools`, `llm_configs`,
`channels`). A category is present only when it has items — an unused secret returns
`{"readable_total": 0, "hidden_total": 0, "categories": []}` and the frontend never renders
an empty group.

**A category the caller cannot read is omitted the same way an empty one is** — never
returned with an empty `items` array, and never distinguished from "unused." That is
deliberate: this endpoint returns resource *names*, so a category present-but-empty would
disclose *which kind* of resource is hiding the secret to a caller who cannot see it.

`readable_total` is the number of items actually listed across `categories`.
`hidden_total` comes from `count_for()`'s `hidden` bucket, **not** from counting anything
`_collect()` gathered — see §3.4 for why that costs a fourth query and why that cost is
accepted rather than avoided.

### 3.1 `_collect` skips unreadable sources before querying, not after

```python
for source in USAGE_SOURCES:
    readability = source.readability(readable_types=readable_types, org_id=org_id)
    if readability == READABLE_NEVER:
        continue
    by_shape[source.detail_shape].append((source, readability))
```

A `READABLE_NEVER` source never reaches `named_rows`/`node_rows`/`edge_rows`, and a
conditional source's rows are filtered (`readable_scoped`, which applies the `Q` as
`.filter()`) before any name is fetched. Nothing readable-but-not-shown ever leaves the
database — the omission in §3 happens at the query, not by discarding rows in Python.

### 3.2 Three query shapes, not nineteen

`_collect` groups sources by `detail_shape` and unions each group:

| Shape | Sources | Columns |
|---|---|---|
| named | up to 13 (fewer when some are `READABLE_NEVER` for this caller) | `(secret_id, category, resource_type, name)` |
| node | 5 | `(secret_id, node_type, graph_id, graph_name, node_name, code_field)` |
| edge | 1 | `(secret_id, node_type, graph_id, graph_name, source_node_id, edge_id, code_field)` |

Sources within a shape already share a column list, so each group unions as-is — no NULL
padding, which is why this beats one nineteen-branch union. Per-source constants
(`node_type`, `code_field`) are projected as columns so the assembler can tell which source a
row came from.

A matching conditional edge adds one more pass: `ConditionalEdge` has no name of its own and
borrows the identity of the node it branches off, so `resolve_node_names` resolves those in
one batched call.

> **`Cast(..., output_field=TextField())` on every name column is required, not cosmetic.**
> `custom_name` is `TextField` on some configs but `CharField` on others, and `name` is
> `TextField` on `PythonCodeTool` but `CharField` on `McpTool`. An uncast union raises
> `FieldError: Expression contains mixed types`.

### 3.3 Ordering is explicit because `UNION` has none

SQL guarantees no row order from a `UNION`, so `_flow_items` and `_named_items` sort
explicitly — flows by `(name, id)`, nodes by `(name, node_type, code_field)`, named items by
name. Without this, two identical calls could return differently-ordered payloads.
`TestSummaryIsDeterministic` covers it.

### 3.4 Why `summary()` costs a fourth query

`_collect` only ever sees readable rows (§3.1), so it cannot supply `hidden_total` — nothing
hidden was fetched to count. `summary()` gets it from a full `count_for()` call instead:

```python
counts = self.count_for(secret=secret, effective=effective)
return {
    "readable_total": sum(len(c["items"]) for c in categories),
    "hidden_total": counts.hidden,
    "categories": categories,
}
```

This is a deliberate, known trade-off, not an oversight: the alternative — running one
unfiltered `_collect()` and partitioning the result in Python — would pull the *names* of
hidden resources into memory to throw them away, one refactor away from a bug that serializes
them. Paying a fourth query to keep those names out of process entirely is the security-
preferred choice. `TestSummaryQueryCost` pins this at four, by name
(`test_four_queries_when_no_conditional_edge_matches`,
`test_four_queries_for_an_unused_secret`), so a future change that reintroduces a Python-side
partition will fail loudly rather than silently reopen this.

### 3.5 `code_field`: which block uses the secret

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
The count is unaffected (§2.5): still one flow, still one distinct key.

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

## 6. Changing a reference vs. reading one: `secrets:USE`

Everything above governs who can **see** that a secret is referenced. A separate mechanism,
`SecretReferenceGuardMixin`, governs who can **change** which secret a resource references —
documented in [DEV_rbac_backend_guide.md](../rbac/DEV_rbac_backend_guide.md) §5.6, not here,
because it is a serializer-layer write guard rather than part of the usage/counting registry.
The short version: a reference is treated as *state*, not an operation — omitted from a
payload or resent unchanged needs nothing; actually changing it requires `secrets:USE`. This
is what makes the guard usable from a bulk graph save, which resubmits the whole graph on
every save.

If you are adding a new secret-referencing field, both mechanisms need updating — see §7,
step 5, and the RBAC guide section above.

---

## 7. Adding a source

1. Append a `UsageSource` to `USAGE_SOURCES` with `model`, `secret_path`, `category`,
   `org_path`, `name_field`, and — for flow nodes — `node_type` and `code_field`.
   A declaration site should instead be added to `PYTHON_CODE_SITES`, which generates its
   source automatically **and** brings the allow-list validator along.
2. **Declare `rbac_resource_types`.** It is a required field with no default, on purpose —
   registering a source without a visibility decision is a bug, not a permissive default. Use
   the `ResourceType` that the source's own endpoint (or nesting serializer) is actually gated
   on. If the resource is reachable through more than one gate — as `NgrokWebhookConfig` and
   `WebhookTriggerAuth` are — see §2.3 before picking a single type.
3. Check which `detail_shape` it lands in. If it introduces a fourth column shape you must
   add a projection method, an assembler, and entries in `SHAPE_PROJECTIONS` /
   `HITS_ASSEMBLERS` — otherwise the union will fail on mismatched columns.
4. `Cast(..., output_field=TextField())` any name column (§3.2).
5. Register the field with `SecretReferenceGuardMixin` too if it is writable — see §6. A
   usage source only makes deletion-safety honest; it does not gate who may repoint the
   reference.
6. Confirm `test_registry_covers_every_declared_source`, `TestDetailShapes`, and
   `tests/services_tests/test_secret_usage_permission_filtering.py` still pass — they assert
   the registry covers every declared site, that each shape's column count is consistent, and
   that the new source's readability resolves correctly for at least one role that can see it
   and one that cannot.
7. If the new model is a graph child that versioning wipes, teach
   `collect_secret_declarations` / `restore_secret_declarations` about it too.
