# Tool Variables — Frontend Integration Guide (EST-1529)

This guide describes what the frontend needs to render and submit for the new `variables`-based Python code tool system.

---

## What changed

| Area | Old UI | New UI |
|------|--------|--------|
| Tool form | Separate "Args Schema" editor + "Config Fields" panel | Single **Variables** list |
| Config form | Generic key-value form validated against Config Fields | Dynamic form rendered from tool's `variables` |
| `PythonCodeToolConfigField` endpoint | `/python-code-tool-config-fields/` (removed) | Gone — all metadata lives in `variables` |

---

## 1. Tool create / edit form — Variables editor

The `variables` field is a list sent as part of `POST /api/python-code-tool/` or `PATCH /api/python-code-tool/{id}/`.

### Fields per variable row

| Field | Control | Visibility |
|-------|---------|------------|
| `name` | Text input | Always |
| `type` | Dropdown | Always |
| `description` | Textarea | Always |
| `input_type` | Dropdown / radio | Always |
| `required` | Checkbox | Always; disable when `input_type === "mixed"` (mixed is never required in schema) |
| `default_value` | Type-sensitive input | Hide when `input_type === "agent_input"` |
| `properties` | Nested key→type editor | Show only when `type === "object"` |
| `required_properties` | Multi-select / tag input | Show only when `type === "object"` |
| `item` | Sub-schema editor | Show only when `type === "array"` |

### Allowed `type` values (for dropdown)

`string`, `number`, `boolean`, `object`, `array`

### Conditional rules summary

```
input_type === "agent_input"
  → hide default_value
  → required checkbox is active

input_type === "user_input"
  → show default_value
  → required checkbox is active (required user_input must be provided via config)

input_type === "mixed"
  → show default_value
  → disable / hide required checkbox (always optional in LLM schema)

type === "object"
  → show properties editor
  → show required_properties picker

type === "array"
  → show item editor
```

### Minimal variable object sent to server

```json
{
  "name": "query",
  "type": "string",
  "description": "Search query from the user",
  "input_type": "agent_input",
  "required": true,
  "default_value": null
}
```

### Full create body example

```http
POST /api/python-code-tool/
Content-Type: application/json

{
  "name": "search_api_tool",
  "description": "Call a search API with user query. Use when asked to search for information.",
  "python_code": {
    "code": "def main(**kwargs):\n    return f\"{kwargs['query']} via {kwargs['api_key']}\"",
    "entrypoint": "main",
    "libraries": [],
    "global_kwargs": {}
  },
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
    },
    {
      "name": "max_results",
      "type": "number",
      "description": "Max results (agent can override, default 10)",
      "input_type": "mixed",
      "required": false,
      "default_value": 10
    }
  ]
}
```

---

## 2. Tool Configuration form (`PythonCodeToolConfig`)

This form lets users provide runtime values for `user_input` and `mixed` variables — per environment, per customer, etc.

### Rendering the form

1. Fetch the tool: `GET /api/python-code-tool/{id}/`
2. From the response, read `variables`.
3. Filter: show only variables where `input_type === "user_input"` or `input_type === "mixed"`.
4. For each variable, render an input control matching its `type`:

| `type` | Control |
|--------|---------|
| `string` | Text input |
| `number` | Number input |
| `boolean` | Toggle / checkbox |
| `object` | JSON textarea |
| `array` | JSON textarea |

5. Mark with asterisk (`*`) if `input_type === "user_input"` and `required === true`.
6. Pre-fill with `default_value` if present (as placeholder or actual value).
7. For editing an existing config: pre-fill from `GET /api/python-code-tool-configs/{id}/` → `configuration` dict.

### Submit

```http
POST /api/python-code-tool-configs/
Content-Type: application/json

{
  "name": "production",
  "tool": 42,
  "configuration": {
    "api_key": "sk-prod-...",
    "max_results": 20
  }
}
```

Only keys that correspond to `user_input` or `mixed` variables should be sent. The server rejects `agent_input` keys with HTTP 400.

### Update

```http
PATCH /api/python-code-tool-configs/{id}/
{ "configuration": { "api_key": "sk-new-..." } }
```

### Server validation errors (HTTP 400)

| Scenario | Error message |
|----------|--------------|
| `agent_input` key in `configuration` | `"Field '<name>' is set by the agent and cannot be configured by the user"` |
| Required `user_input` variable missing | `"Field '<name>' is required"` |
| Type mismatch (primitive) | `"Error casting value '<value>' into '<type>'"` |
| Type mismatch (object) | `"Expected an object, got '<actual_type>'"` |
| Type mismatch (array) | `"Expected an array, got '<actual_type>'"` |

---

## 3. Agent form — Wiring tool references

An agent's `tool_ids` array takes strings in one of two formats:

| Format | Meaning |
|--------|---------|
| `"python-code-tool:<id>"` | Use the tool with its own `default_value` fallbacks |
| `"python-code-tool-config:<config_id>"` | Use a `PythonCodeToolConfig` (overrides defaults) |

### Suggested UX flow

1. Show a list of available tools: `GET /api/python-code-tool/`
2. When the user picks a tool, query its configs: `GET /api/python-code-tool-configs/?tool=<id>`
3. If configs exist, show a "Select configuration (optional)" dropdown.
   - No selection → submit `"python-code-tool:<id>"`
   - Config selected → submit `"python-code-tool-config:<config_id>"`
4. If no configs exist (or the tool has no `user_input`/`mixed` variables), skip the dropdown.

```jsonc
// Example agent payload
{
  "role": "Researcher",
  "tool_ids": [
    "python-code-tool:5",           // tool with no config needed (only agent_input vars)
    "python-code-tool-config:12"    // tool with user_input vars, using config #12
  ]
}
```

---

## 4. Tool detail / read-only view

When displaying a tool's variables (e.g., on a detail page or tooltip), suggest this layout per variable:

```
[AGENT]   query       string    required    "Search query from the user"
[USER]    api_key     string    required    "API key"
[MIXED]   max_results number    optional    default: 10   "Max results"
```

Badge colours (suggestion):
- `AGENT` → blue (LLM-controlled)
- `USER` → amber (admin-configured)
- `MIXED` → green (LLM-optional, server fallback)

---

## 5. Import / Export

The `variables` field is included in tool export payloads by default. No special handling is needed — it serializes as a plain JSON array alongside the other tool fields.

Old exports that contain `args_schema` or reference `python-code-tool-config-fields` are from before the migration and are no longer valid.

---

## Quick reference: endpoints

| Endpoint | Used for |
|----------|----------|
| `GET /api/python-code-tool/` | List tools for picker |
| `POST /api/python-code-tool/` | Create tool |
| `GET /api/python-code-tool/{id}/` | Read variables to build config form |
| `PUT/PATCH /api/python-code-tool/{id}/` | Update tool variables |
| `POST /api/python-code-tool/{id}/copy/` | Duplicate tool |
| `GET /api/python-code-tool-configs/` | List configs (optionally filter by `?tool=<id>`) |
| `POST /api/python-code-tool-configs/` | Create config |
| `GET /api/python-code-tool-configs/{id}/` | Load existing config values |
| `PUT/PATCH /api/python-code-tool-configs/{id}/` | Update config |
| `DELETE /api/python-code-tool-configs/{id}/` | Delete config |
