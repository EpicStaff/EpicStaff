# Classification Decision Table Node

A graph node type that evaluates tabular decision logic with Python expressions, LLM prompts, and pre/post computation hooks. Extends the simpler `DecisionTableNode` with multi-column conditions, continue/stop flow control, field-level expressions and manipulations, and per-row routing.

**Source files:**
- Backend engine: `src/crew/services/graph/subgraphs/classification_decision_table_node.py`
- Django model: `src/django_app/tables/models/graph_models.py` (`ClassificationDecisionTableNode`, `ClassificationConditionGroup`, `ClassificationDecisionTablePrompt`)
- Crew runtime data model: `src/shared/models/graph_nodes.py` (`ClassificationDecisionTableNodeData`, `ClassificationConditionGroupData`, `PromptConfigData`)
- Graph builder / routing: `src/crew/services/graph/graph_builder.py` (`add_classification_decision_table_node`)

## How It Works

A CDT node runs as a LangGraph subgraph with two internal steps:

```
START → enter (pre-computation) → evaluate (rows + post-computation) → END
```

1. **Pre-computation** (`enter` node) — runs sandboxed Python (`main()`) to prepare variables before table evaluation. On error → `result_node = next_error_node or END` and row evaluation is skipped.
2. **Row evaluation** (`evaluate` node) — condition groups are evaluated top-to-bottom by `order`. Each row has field expressions (AND-combined), an optional main expression, an optional LLM prompt, manipulation code, an optional `next_node` (routing target), and a continue flag.
3. **Post-computation** — runs after routing is decided. Does not influence routing (except: on error → `next_error_node`/`END`).
4. **Routing** — the parent graph reads the CDT's `result_node` from `system_variables` and routes there; falls back to `default_next_node`. See **Routing** below.

## Node Configuration

`ClassificationDecisionTableNodeData` (`src/shared/models/graph_nodes.py`):

```python
class ClassificationDecisionTableNodeData(BaseModel):
    node_name: str
    pre_python_code: PythonCodeData | None = None    # sandboxed code w/ main()
    pre_input_map: dict[str, str] = {}               # "local_name": "variables.path"
    pre_output_variable_path: str | None = None      # where to store main() return
    post_python_code: PythonCodeData | None = None   # same pattern as pre
    post_input_map: dict[str, str] = {}
    post_output_variable_path: str | None = None
    condition_groups: list[ClassificationConditionGroupData] = []
    prompts: dict[str, PromptConfigData] = {}         # prompt library keyed by id
    default_next_node: str | None = None
    next_error_node: str | None = None
```

> Note: there is no `route_variable_name`, `route_map`, or `expression_errors_as_false` — those were removed (migrations 0172/0174). Routing is purely `next_node`-based (below).

## Condition Groups (Rows)

`ClassificationConditionGroupData` (`src/shared/models/graph_nodes.py`):

```python
class ClassificationConditionGroupData(BaseModel):
    group_name: str
    expression: str | None = None                 # main Python expression (optional)
    prompt_id: str | None = None                  # reference into node `prompts`
    manipulation: str | None = None               # main Python manipulation code
    continue_flag: bool = False                   # after a MATCH: True=continue, False=stop
    next_node: str | None = None                  # routing target (resolved node name)
    dock_visible: bool = True                     # enabled flag (see below)
    order: int = 0                                # evaluation order
    field_expressions: dict[str, str] = {}        # column → expression fragment
    field_manipulations: dict[str, str] = {}      # column → assignment expression
```

### Field Expression Formats

Field expressions are AND-combined, then the main `expression` is AND-appended. Format options:
- **Bare value**: `"start"` → `field == "start"`
- **Operator prefix**: `> 5`, `!= "end"`, `in ("a", "b")` → `field > 5`
- **Full expression**: `field > 0 and field < 10` → used as-is

Empty/None expressions evaluate as `True` — a row with only field_expressions matches if those pass; a row with no expressions at all always matches.

### Evaluation Flow Per Row

1. Build the combined expression (`field_expressions` AND-joined, then `expression`).
2. Evaluate it in the sandbox. **False ⇒ skip the row entirely** (no prompt, no manipulation, no routing capture).
3. **Match (True):**
   - Execute the LLM prompt if `prompt_id` is set.
   - Execute the combined manipulation (`field_manipulations` + `manipulation`); changes are written back to state.
   - If `next_node` is set, capture it as the routing target (overwrites any prior).
   - If `continue_flag` is `False` → **stop**. If `True` → continue to the next row.

`continue_flag` is consulted **only after a row matches**. A non-matching row always falls through to the next row regardless of `continue_flag`.

### Routing

There is **no** route-code/route-map lookup. Each matched row's `next_node` (a resolved graph node-name string, derived from `next_node_id` by the Django→pydantic converter) is the routing target.

Priority after all rows are evaluated:

```
last matched row's next_node  >  default_next_node  >  END
errors (pre-comp / expression / manipulation / prompt / post-comp)  ⇒  next_error_node  >  END
```

With `continue_flag = True`, the **last** matching row that has a non-null `next_node` wins; a later matching row whose `next_node` is null does **not** clear a previously-captured target. The engine sets `system_variables[node]["result_node"]`, and `add_classification_decision_table_node` (graph_builder.py) returns `result_node or default_next_node`.

> `route_code` exists on the Django model but is a **frontend-only** identifier (the canvas output-port id). It is not in the runtime pydantic model and the engine never reads it.

### Enabled / disabled rows (`dock_visible`)

`dock_visible=False` means the row is **disabled**: `build()` filters those groups out before evaluation, so a disabled row is never evaluated and its prompt/manipulation never run. (On the frontend it also hides the row's output port.)

## Pre/Post Computation

`pre_python_code` / `post_python_code` are `PythonCodeData` objects (`venv_name`, `code`, `entrypoint`, `libraries`). They run in the **same sandbox** as expressions/manipulations via `RunPythonCodeService` (not in-process `exec()`):

1. The input map is resolved into kwargs and passed to the entrypoint (`main`).
2. The return value is stored via `set_output_variables` at `output_variable_path`.

### Input Map Path Resolution

`_resolve_input_map` / `_resolve_path` (no `eval()`) resolve `input_map` values against state. Supports dot access (`variables.chat_id`) and bracket access with dynamic keys (`variables.shared[variables.chat_id].inbox`). Resolve context is limited to: `variables`, `system_variables`, `session_id`, `node_name`.

## Expressions and Manipulations (Sandboxed)

Row expressions and manipulations run in a sandboxed subprocess via `RunPythonCodeService`:

- State variables are serialized into the sandbox as a dict and exposed as a `SimpleNamespace` (`variables`) for dot access; referencing a variable that isn't present raises `AttributeError`.
- Expressions must return `bool`.
- Manipulations modify `variables`; changes are written back to state.
- The `shared` proxy is stripped before serialization (not available in the sandbox).

## LLM Prompts

Prompts live in the `prompts` dict on the node, keyed by id:

```python
class PromptConfigData(BaseModel):
    prompt_text: str                       # template with {var_name} interpolation
    llm_id: int | None = None
    output_schema: dict | str = {}         # JSON Schema for structured output
    result_variable: str = "prompt_result" # state variable to store the result
    variable_mappings: dict[str, str] = {} # extract fields: state_var → result_field
    llm_data: LLMData | None = None         # resolved at runtime
```

The prompt is rendered with `str.format(**variables)` and sent via `litellm.acompletion`. When `output_schema` is non-empty it is applied as a `response_format` of `{"type": "json_schema", "json_schema": {"name": ..., "schema": <output_schema>, "strict": True}}`; a string schema is JSON-parsed first. If `output_schema` is empty or invalid JSON, the request is sent without `response_format`. The response is parsed via `extract_first_json_object`, stored at `result_variable`, and `variable_mappings` extract individual fields into other state variables.

## Message Ordering

CDT messages (start, condition-group result, manipulation, prompt, finish) are tagged with a global monotonic `execution_order` (one value per CDT iteration), shared with all other nodes via `system_variables["execution_order"]`, so the session timeline orders correctly across loops and subflows.

## Export

A CDT node can be exported on its own via `GET /api/classification-decision-table-node/{id}/export`. The `export_format` query parameter selects the output:

```
GET /api/classification-decision-table-node/{id}/export?export_format=json   # default
GET /api/classification-decision-table-node/{id}/export?export_format=csv
```

### JSON (`export_format=json`, default)

Reuses the partial-export pipeline (`GraphPartialExportService`), so the file is structurally identical to a [partial node export](../import_export/PARTIAL_NODE_IMPORT_EXPORT.md) of a single CDT node — the node plus its transitive dependencies (LLM configs, prompts' configs, referenced Python code). Because of this, a JSON export **is re-importable** into any existing graph via the graph `partial-import` endpoint.

The filename is prefixed `CDT_` (e.g. `CDT_my_node_20260611.json`).

### CSV (`export_format=csv`)

Produced by `export_condition_groups_csv()` in `tables/import_export/tabular/classification_decision_table.py`. This is a **read-only, human-readable report** — it flattens the node's rules into a spreadsheet and **cannot be re-imported**. Use it for review, sharing, or auditing decision logic outside the app.

The file is laid out as several labelled sections:

| Section | Contents |
|---|---|
| `CLASSIFICATION DECISION TABLE` | Node-level summary: node name, default AI model, whether pre/post scripts exist, default next step, on-error step, rule count |
| `AI MODELS USED` | One row per distinct LLM config referenced by the node or its rows — columns: Configuration Name, Model, Temperature, Max Tokens |
| `DECISION RULES` | One row per condition group |

Each rule row in the `DECISION RULES` section has these columns:

```
#, Rule Name, Section, Route Code, Condition, AI Prompt, AI Model,
Saves Result To, Action, Field Conditions, Field Actions,
Continue After Match, Next Step
```

Notes on formatting:
- Field-level mappings (`Field Conditions`, `Field Actions`) are rendered as newline-joined `key: value` pairs within a single cell.
- Node references (`Next Step`, and the node-level next/error steps) are resolved to the target node's `node_name`, falling back to `node #<id>` when the name is unavailable.
- `Continue After Match` is rendered as `Yes` / `No`.

The filename is `CDT_<node_name>.csv`.

## DB Schema

```
ClassificationDecisionTableNode
├── graph (FK → Graph)
├── node_name (unique per graph)
├── pre_python_code, post_python_code (FK → PythonCode)
├── pre_input_map, pre_output_variable_path
├── post_input_map, post_output_variable_path
├── default_next_node, next_error_node, default_llm_config
├── condition_groups → ClassificationConditionGroup[]
│   ├── group_name, order
│   ├── expression, field_expressions (JSON)
│   ├── prompt_id
│   ├── manipulation, field_manipulations (JSON)
│   ├── continue_flag
│   ├── next_node_id        # routing target (the field the engine uses)
│   ├── dock_visible        # enabled/disabled
│   ├── route_code          # frontend port id (unused at runtime)
│   └── section             # frontend visual grouping
└── prompt_configs → ClassificationDecisionTablePrompt[]
    ├── prompt_key, prompt_text, llm_config (FK)
    ├── output_schema (JSON)
    ├── result_variable, variable_mappings (JSON)
```

API: `POST/GET/DELETE /api/classification-decision-table-node/`

## Error Handling

- Pre-computation errors → `next_error_node` (or `END`); row evaluation is skipped.
- Expression / manipulation / prompt errors during a row → `next_error_node` (or `END`); reported as `Error in condition '<group_name>': ...`.
- Post-computation errors → `next_error_node` (or `END`).

## Tests

`src/crew/tests/graph/subgraphs/test_classification_decision_table_node.py` covers routing (first-match, fall-through, continue/last-match-wins, default, error→next_error_node), `dock_visible` skipping, field expressions, manipulation write-back, and prompt `output_schema` application. The sandbox (`RunPythonCodeService.run_code`) and `litellm.acompletion` are mocked.
