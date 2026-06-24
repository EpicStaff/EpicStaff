# Tool Variables Configuration (EST-1529)

Python code tools use a unified **`variables`** field to define every input a tool accepts. A single list replaces the old two-table system (`args_schema` + `PythonCodeToolConfigField`) and controls, per-variable, whether the LLM sees it, the user configures it, or both.

---

## Variable object schema

Each entry in the top-level `variables` list is a JSON object:

```jsonc
{
  "name": "query",              // identifier — must match the kwarg name in main(**kwargs)
  "type": "string",             // see allowed values below
  "description": "...",         // shown to LLM; write clear descriptions for better tool calls
  "input_type": "agent_input",  // routing rule: "agent_input" | "user_input" | "mixed"
  "required": true,             // only enforced for agent_input in the LLM schema
  "default_value": null,        // fallback injected server-side for user_input and mixed

  // when type = "object" — both `properties` and `required_properties` are required:
  "properties": {               // map of field name → nested descriptor (see "Nested descriptors" below)
    "key": { "type": "string", "description": "..." }
  },
  "required_properties": [      // list of field names from `properties` that must be present;
    "key"                       // pass [] if no field is required
  ],

  // when type = "array" — `item` is required:
  "item": {                     // nested descriptor for each element; the array is homogeneous
    "type": "string",
    "description": "..."
  }
}
```

**Allowed `type` values:** `string`, `number`, `boolean`, `object`, `array`

### Nested descriptors

Values inside `properties` and `item` are **nested descriptors** — same shape as a top-level variable but **without** `name`, `input_type`, and `required` (these only make sense at the top level, where the variable participates in tool routing). A nested descriptor has:

| Field | Required | Notes |
|---|---|---|
| `type` | yes | One of the 5 allowed values |
| `description` | no | Shown to LLM; defaults to empty |
| `default_value` | no | Same semantics as top-level |
| `properties` + `required_properties` | only if `type === "object"` | Both required when type is `object` |
| `item` | only if `type === "array"` | Required when type is `array` |

Nesting can go arbitrarily deep: object inside object, array of objects, array of arrays.

### Full example

A tool variable describing a user profile with three primitive fields, a nested object (`address`), and a nested array of strings (`tags`):

```jsonc
{
  "name": "user",
  "type": "object",
  "description": "User profile to look up",
  "input_type": "agent_input",
  "required": true,

  "default_value": {                       // plain JSON object — no descriptor metadata inside
    "username": "rick",
    "age": 70,
    "address": { "city": "Berlin", "zip": "10115" },
    "tags": ["admin", "active"]
  },

  "properties": {
    "username": {
      "type": "string",
      "description": "Login identifier"
    },
    "age": {
      "type": "number",
      "description": "Age in years"
    },
    "address": {                           // nested object — recursive structure
      "type": "object",
      "description": "Mailing address",
      "properties": {
        "city": { "type": "string", "description": "City name" },
        "zip":  { "type": "string", "description": "Postal code" }
      },
      "required_properties": ["city"]      // empty array is also valid: []
    },
    "tags": {                              // array of strings
      "type": "array",
      "description": "User tags",
      "item": {
        "type": "string",
        "description": "Single tag"
      }
    }
  },
  "required_properties": ["username", "address"]
}
```

Note the separation:
- **`properties` / `item`** describe the **structure** (recursive — values are again descriptors)
- **`default_value`** holds the **literal data** (a plain JSON dict/list/value — no `"type"` keys inside)

---

## `input_type` — the routing field

| `input_type`  | In LLM args schema | In sandbox `kwargs` | Required in schema |
|---------------|--------------------|---------------------|--------------------|
| `agent_input` | Yes | Via agent call | Yes, if `required: true` |
| `user_input`  | No  | Via `global_kwargs` (default or config) | Never |
| `mixed`       | Yes (always optional) | Both paths — agent value wins | Never |

---

## Runtime data flow

```
Tool definition (variables list)
           │
           ▼
    converter_service
    ┌──────────────────────────────────────────────┐
    │  builds args_schema                           │
    │    ← agent_input + mixed variables only       │
    │    ← mixed variables are never "required"     │
    │                                               │
    │  builds global_kwargs                         │
    │    ← user_input + mixed default_values        │
    │    ← PythonCodeToolConfig overrides on top    │
    └──────────────────────────────────────────────┘
           │                       │
           ▼                       ▼
    LLM tool schema          global_kwargs
    (what agent sees)        (server-side injection)
           │                       │
           └──────────┬────────────┘
                      ▼
             sandbox execution
             main(**{**global_kwargs, **agent_kwargs})
```

**Override priority (highest wins):**
agent-provided kwargs > PythonCodeToolConfig values > variable `default_value`

---

## Python types in `main()`

When a variable's `type` is `object` or `array`, the value passed to `main(**kwargs)` is wrapped:

| Variable `type` | Python type received by `main()` |
|----|----|
| `string` | `str` |
| `number` | `int` or `float` |
| `boolean` | `bool` |
| `object` | `DotDict` (attribute access supported) |
| `array` | `DotList` |

`DotDict` and `DotList` come from `shared.dotdict` and allow attribute-style access into nested data:

```python
# Variable: { "name": "user", "type": "object", ... }
def main(**kwargs):
    return kwargs["user"].name        # attribute access works
    # equivalent to kwargs["user"]["name"]
```

For nested `object`-in-`array` or `array`-in-`object` structures, the wrapping is applied recursively.

---

## Use cases

### 1. All agent_input — LLM must supply everything

The LLM is responsible for all arguments. No server-side injection.

```json
{
  "name": "name_formatter",
  "description": "Combine a first and last name.",
  "variables": [
    {
      "name": "first_name",
      "type": "string",
      "description": "Person's first name",
      "input_type": "agent_input",
      "required": true,
      "default_value": null
    },
    {
      "name": "last_name",
      "type": "string",
      "description": "Person's last name",
      "input_type": "agent_input",
      "required": true,
      "default_value": null
    }
  ]
}
```

LLM schema produced:
```json
{
  "properties": {
    "first_name": { "type": "string", "description": "Person's first name" },
    "last_name":  { "type": "string", "description": "Person's last name"  }
  },
  "required": ["first_name", "last_name"]
}
```

```python
def main(**kwargs):
    return f"{kwargs['first_name']} {kwargs['last_name']}"
```

---

### 2. user_input with default — injected silently

The variable is invisible to the LLM. The `default_value` is injected automatically. No `PythonCodeToolConfig` needed.

```json
{
  "variables": [
    {
      "name": "item",
      "type": "string",
      "description": "Item to process",
      "input_type": "agent_input",
      "required": true,
      "default_value": null
    },
    {
      "name": "suffix",
      "type": "string",
      "description": "Suffix appended server-side",
      "input_type": "user_input",
      "required": false,
      "default_value": "_done"
    }
  ]
}
```

The LLM only sees `item`. At runtime, `suffix="_done"` arrives via `global_kwargs`:

```python
def main(**kwargs):
    return kwargs["item"] + kwargs.get("suffix", "")
# result: "hello_done"
```

---

### 3. user_input with PythonCodeToolConfig override — per-deployment secrets

Use this when the variable has no safe default (e.g., an API key) or when different deployments need different values.

**Step 1 — Define the tool:**
```json
{
  "variables": [
    {
      "name": "query",
      "type": "string",
      "description": "Search query",
      "input_type": "agent_input",
      "required": true,
      "default_value": null
    },
    {
      "name": "api_key",
      "type": "string",
      "description": "API key for the search service",
      "input_type": "user_input",
      "required": true,
      "default_value": null
    }
  ]
}
```

**Step 2 — Create a config:**
```http
POST /api/python-code-tool-configs/
{
  "name": "production",
  "tool": 42,
  "configuration": {
    "api_key": "sk-prod-..."
  }
}
```

**Step 3 — Assign to agent using config ID:**
```json
{ "tool_ids": ["python-code-tool-config:7"] }
```

At runtime: `api_key="sk-prod-..."` arrives via `global_kwargs`; LLM never sees it.

Validation rules for `configuration`:
- Only `user_input` and `mixed` variables may appear in `configuration`
- Sending an `agent_input` variable key → HTTP 400
- Missing a required `user_input` variable → HTTP 400
- Type mismatch (e.g., string for a number field) → HTTP 400

---

### 4. mixed — LLM can override a server default

The LLM sees the variable as optional (never required) and may pass a value. If it doesn't, `default_value` is used.

```json
{
  "variables": [
    {
      "name": "item",
      "type": "string",
      "description": "Item to repeat",
      "input_type": "agent_input",
      "required": true,
      "default_value": null
    },
    {
      "name": "count",
      "type": "number",
      "description": "How many times to repeat (default: 3)",
      "input_type": "mixed",
      "required": false,
      "default_value": 3
    }
  ]
}
```

LLM schema for `count`:
```json
"count": { "type": "number", "description": "How many times to repeat (default: 3)", "default": 3 }
```

The variable is not in `required`. If the agent omits it, the sandbox receives `count=3` from `global_kwargs`. If the agent passes `count=7`, the agent value wins.

```python
def main(**kwargs):
    return f"{kwargs['item']}*{kwargs.get('count', 1)}"
```

---

## API reference

### `/api/python-code-tool/`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/python-code-tool/` | List all tools; response includes full `variables` array |
| `POST` | `/api/python-code-tool/` | Create a tool; `name`, `description`, `python_code`, `variables` required |
| `GET` | `/api/python-code-tool/{id}/` | Retrieve single tool |
| `PUT` | `/api/python-code-tool/{id}/` | Full update (rejected for built-in tools) |
| `PATCH` | `/api/python-code-tool/{id}/` | Partial update (rejected for built-in tools) |
| `DELETE` | `/api/python-code-tool/{id}/` | Delete (rejected for built-in tools) |
| `POST` | `/api/python-code-tool/{id}/copy/` | Duplicate tool; `variables` are copied as-is |

Minimal create body:
```json
{
  "name": "my_tool",
  "description": "What this tool does (shown to LLM).",
  "python_code": {
    "code": "def main(**kwargs): return str(kwargs)",
    "entrypoint": "main",
    "libraries": [],
    "global_kwargs": {}
  },
  "variables": []
}
```

### `/api/python-code-tool-configs/`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/python-code-tool-configs/` | List all configs |
| `POST` | `/api/python-code-tool-configs/` | Create config; validated against tool's variables |
| `GET` | `/api/python-code-tool-configs/{id}/` | Retrieve config |
| `PUT` | `/api/python-code-tool-configs/{id}/` | Full update (re-validates) |
| `PATCH` | `/api/python-code-tool-configs/{id}/` | Partial update (re-validates) |
| `DELETE` | `/api/python-code-tool-configs/{id}/` | Delete |

### Referencing a tool from an Agent

```json
{
  "tool_ids": [
    "python-code-tool:42",          // use tool defaults
    "python-code-tool-config:7"     // use a specific config
  ]
}
```

---

## Migration from the old system

Before EST-1529, tools used two separate mechanisms:

| Old | New |
|-----|-----|
| `PythonCodeTool.args_schema` (JSON Schema) | Variables with `input_type: "agent_input"` |
| `PythonCodeToolConfigField` records | Variables with `input_type: "user_input"` |
| `PythonCodeToolConfigField.default_value` | Variable's `default_value` |

Migration `0170_pythoncodetool_variables_drop_args_schema` converted all existing data automatically:
- Each `args_schema.properties` entry → `agent_input` variable
- Each `PythonCodeToolConfigField` row → `user_input` variable
- `args_schema` column and `PythonCodeToolConfigField` table were removed

Built-in tools are re-uploaded on every `upload_models` run and receive their variables from their bundled metadata.
