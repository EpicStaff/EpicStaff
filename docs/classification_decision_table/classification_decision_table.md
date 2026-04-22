# Classification Decision Table Node

A graph node type that evaluates tabular decision logic with Python expressions, LLM prompts, and pre/post computation hooks. Extends the simpler `DecisionTableNode` with multi-column conditions, continue/stop flow control, field-level expressions and manipulations, and shared variable integration.

**Source files:**
- Backend engine: `src/crew/services/graph/subgraphs/classification_decision_table_node.py`
- Django model: `src/django_app/tables/models/graph_models.py` (`ClassificationDecisionTableNode`, `ClassificationConditionGroup`)
- Crew data model: `src/crew/models/request_models.py` (`ClassificationDecisionTableNodeData`)
- Frontend service: `frontend/.../services/classification-decision-table-node.service.ts`
- Graph builder: `src/crew/services/graph/graph_builder.py` (`add_classification_decision_table_node`)
- Route map builder: `src/django_app/tables/services/session_manager_service.py` (`_build_route_maps`)

## How It Works

A CDT node runs as a LangGraph subgraph with two internal steps:

```
START → enter (pre-computation) → evaluate (rows + post-computation) → END
```

1. **Pre-computation** — runs sandboxed Python code (`main()` function) to prepare variables before table evaluation. Input map resolves state paths into kwargs; output stored via `set_output_variables`. Supports two-phase execution (`needs_rerun`).
2. **Row evaluation** — condition groups evaluated top-to-bottom. Each row has field expressions (AND-combined), an optional main expression, an optional LLM prompt, manipulation code, a route code, and a continue flag.
3. **Post-computation** — runs after the matched route is determined. Used for state updates (shared variable writes, data transformations). Does not influence routing.
4. **Routing** — the final `route_code` is resolved to an actual graph node name via `route_map` (built at session start from graph metadata connections). Falls back to `default_next_node`.

## Node Configuration

```python
ClassificationDecisionTableNodeData:
    node_name: str
    pre_computation_code: str | None       # Python code with main() function
    pre_input_map: dict[str, str]          # "local_name": "variables.path.to.value"
    pre_output_variable_path: str | None   # where to store main() return value
    post_computation_code: str | None      # same pattern as pre
    post_input_map: dict[str, str]
    post_output_variable_path: str | None
    condition_groups: list[ClassificationConditionGroupData]
    prompts: dict[str, PromptConfigData]   # prompt library keyed by ID
    route_variable_name: str = "route_code"
    route_map: dict[str, str]              # route_code → node_name (built at runtime)
    default_next_node: str | None
    next_error_node: str | None
    expression_errors_as_false: bool = False
```

## Condition Groups (Rows)

Each row is a `ClassificationConditionGroupData`:

```python
    group_name: str                        # human-readable label
    expression: str | None                 # main Python expression (optional)
    field_expressions: dict[str, str]      # column_name → expression fragment
    prompt_id: str | None                  # reference to prompts dict
    manipulation: str | None               # main Python manipulation code
    field_manipulations: dict[str, str]    # column_name → assignment expression
    continue_flag: bool = False            # True = continue to next row; False = stop
    route_code: str | None                 # route code if this row matches
    dock_visible: bool = True              # whether output port is visible in UI
    order: int = 0                         # evaluation order
```

### Field Expression Formats

Field expressions are combined with AND logic. Format options:
- **Bare value**: `"start"` → `field == "start"`
- **Operator prefix**: `> 5`, `!= "end"`, `in ("a", "b")` → `field > 5`
- **Full expression**: `field > 0 and field < 10` → used as-is

Empty/None expressions evaluate as `True` — rows with only field_expressions and no main expression match if the field conditions pass.

### Evaluation Flow Per Row

1. Build combined expression from `field_expressions` + `expression` (AND-joined)
2. If expression is true (or empty):
   - Execute LLM prompt if `prompt_id` is set
   - Execute combined manipulation from `field_manipulations` + `manipulation`
   - Capture `route_code` if set
3. If `continue_flag` is `True` → evaluate next row. If `False` → stop.

### Route Priority

After all rows are evaluated: `variable route_code > matched row route_code > default_next_node`.

## Pre/Post Computation

Both run in-process (not sandboxed) using the `main()` function pattern:

1. `exec(code)` defines `main()`
2. `main(**input_map_kwargs)` is called with resolved input map values
3. Return value stored via `set_output_variables` at `output_variable_path`

### Input Map Path Resolution

Uses `_resolve_path()` — no `eval()`. Supports:
- Dot access: `variables.chat_id`
- Bracket access with dynamic key: `variables.shared[variables.chat_id].inbox_messages`
- Default values via pipe syntax: `variables.shared[variables.chat_id].counter|0` (resolved by `set_output_variables`)

Available in resolve context: `variables`, `system_variables`, `redis_service`, `session_id`, `node_name`, `logger`, `time`, `json`, `uuid`.

### Shared Variable Integration

Pre/post computation can interact with shared variables via special return keys:

- **`shared_append`** — atomic list append: `{"shared_append": {access_key: {"var_name": [items]}}}`
- **`shared_claim`** — atomic SETNX: `{"shared_claim": {access_key: {"var_name": value}}}` or `{"var_name": {"value": X, "ttl": seconds}}`
- **`needs_rerun`** — if `True`, shared cache is cleared and pre-computation re-runs (two-phase pattern for leader election)

Claim results are injected back as `result["claim_results"] = {"var_name": True/False}`.

## Expressions and Manipulations (Sandboxed)

Unlike pre/post computation, row expressions and manipulations run in a **sandboxed subprocess** via `RunPythonCodeService`:

- State variables are serialized into the sandbox as a dict
- Variables are converted to `SimpleNamespace` for dot-access syntax
- Expressions must return `bool`
- Manipulations can modify variables; changes are written back to state
- `shared` proxy is stripped before serialization (not available in sandbox)

## LLM Prompts

Prompts are stored in a `prompts` dict on the node, keyed by ID:

```python
PromptConfigData:
    prompt_text: str                  # template with {var_name} interpolation
    llm_id: str                       # reference to LLM config
    output_schema: dict | str         # expected output format
    result_variable: str              # state variable to store parsed result
    variable_mappings: dict[str, str] # extract fields: state_var → result_field
    llm_data: LLMData | None          # resolved at runtime
```

The prompt is rendered with `str.format(**variables)`, sent via `litellm.acompletion`, and the JSON response is parsed and stored in `state["variables"][result_variable]`.

## Route Map (Runtime)

Route codes from CDT rows are abstract labels (e.g. `PASS_THROUGH`, `CONDENSED`). They're mapped to actual graph node names at session start by `_build_route_maps()` in `session_manager_service.py`.

The mapping is derived from graph metadata connections: each CDT output port has an ID like `{node_uuid}_decision-route-{route_code}`. The target node of each such connection gives the route_code → node_name mapping.

In `graph_builder.py`, conditional edges use this `route_map` to resolve the CDT's `result_node` to an actual LangGraph node name, with case-insensitive fallback.

## Frontend Save/Load

`save-graph.service.ts` handles CDT nodes in the delete-then-recreate cycle via `deleteAndRecreate`. The payload is built by `ClassificationDecisionTableNodeService.buildCreatePayload()`:

- Reads table config from `node.data.table` in graph metadata
- Serializes field_expressions from `{field, operator, value}` objects to string format
- Preserves pre/post computation code, input maps, and output variable paths
- Resolves `default_next_node` and `next_error_node` via `resolveNodeName`
- CDT source ports are preserved during `clearNodePorts` (not stripped like regular nodes)
- Edges from CDT source nodes are skipped in normal edge creation (CDT handles its own routing)

## Error Handling

- **`expression_errors_as_false`** — if `True`, expression errors are logged as warnings and the row is treated as non-matching instead of aborting
- Pre/post computation errors route to `next_error_node` (or `END`)
- Row evaluation errors route to `next_error_node` (unless `expression_errors_as_false`)

## DB Schema

```
ClassificationDecisionTableNode
├── graph (FK → Graph)
├── node_name (unique per graph)
├── pre_computation_code, pre_input_map, pre_output_variable_path
├── post_computation_code, post_input_map, post_output_variable_path
├── prompts (JSON)
├── route_variable_name (default: "route_code")
├── default_next_node, next_error_node
├── expression_errors_as_false
└── condition_groups → ClassificationConditionGroup[]
    ├── group_name, order
    ├── expression, field_expressions (JSON)
    ├── prompt_id
    ├── manipulation, field_manipulations (JSON)
    ├── continue_flag, route_code, dock_visible
```

API: `POST/GET/DELETE /api/classification-decision-table-node/`
