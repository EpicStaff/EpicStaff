---
id: epicchat-response
name: EpicChat Response Format
version: 1.1
trigger: always_on
triggers: [epicchat, response, tables, actions, buttons]
scope: [output, format, widget]
description: How to format structured JSON responses for the EpicChat widget — message text, tables, action buttons, navigation, prompt suggestions, and tool toggles. Use this skill whenever producing output for EpicChat.
---

# EpicChat Response Format

Your structured output is rendered by the EpicChat widget. Return only the fields you need — `message` is the only required field.

## Fields

### `message` (string, required)
Main chat reply. Full Markdown supported (headings, bold, code blocks, lists, links).

### `tools` (string[], required if configured)
Tool toggles shown in the input area dropdown. Include `["Build mode"]` to keep the build/plan toggle active.

### `ef_tables` (array, optional)
Interactive data tables rendered below the message.

**Minimal** — just rows, columns auto-detected:
```json
{
  "ef_tables": [{
    "rows": [
      {"name": "Alice", "score": 95, "passed": true},
      {"name": "Bob", "score": 72, "passed": false}
    ]
  }]
}
```

**With options:**
```json
{
  "ef_tables": [{
    "columns": [
      {"key": "name", "title": "Name", "editable": false},
      {"key": "score", "title": "Score", "type": "number"}
    ],
    "rows": [{"name": "Alice", "score": 95}],
    "isEditable": false,
    "isSortable": true,
    "rowsSelectionType": "select"
  }]
}
```

Table options: `id`, `isEditable` (default true), `isSortable` (default true), `defaultSortField`, `rowsSelectionType` ("edit" | "select" | "multiSelect"), `preselectedRows`, `unions` ({title, keys}[]).

Column options: `key`, `title`, `type` ("text" | "number" | "boolean" | "date"), `visible`, `editable`.

### `action_message` (array, optional)
Interactive elements displayed with the message.

```json
{
  "action_message": [
    {"type": "button", "action": "sendAction", "text": "Do something"},
    {"type": "link", "action": "link", "text": "Open docs", "params": {"url": "https://..."}},
    {"type": "prompt", "text": "Try asking about X"}
  ]
}
```

| type | behavior |
|---|---|
| `button` | Clickable button below message. Removed after click. Sends `text` as `user_action`. |
| `link` | Opens `params.url` in browser. |
| `prompt` | Suggestion chip in input footer. Clicking sends `text` as new user message. |

### Action identifiers

| `action` value | When to use |
|---|---|
| `sendAction` | Default for buttons. Sends `text` as `user_action` to the flow. |
| `sendButtonTextWithParams` | Like `sendAction` but also sends `params` as context extras — use when the button carries structured data beyond the label. |
| `processTables` | Sends edited/selected table data back to the flow. Use with `rowsSelectionType: "select"` or `"multiSelect"` tables so the user can pick rows and submit. |
| `link` | Opens `params.url` in browser. |
| `openFlow` | Navigates to a flow. Requires `params: {"flowId": "<id>"}`. |
| `openNode` | Opens a node panel. Requires `params: {"flowId": "<id>", "nodeId": "<uuid>"}`. |
| `refreshCache` | Reloads the page to pick up flow/node changes. |

### Navigation actions

Use these to help the user navigate the EpicStaff UI after creating/modifying flows:

```json
{"type": "button", "text": "Open flow 55", "action": "openFlow", "params": {"flowId": "55"}}
{"type": "button", "text": "Open Code Agent", "action": "openNode", "params": {"flowId": "55", "nodeId": "<uuid>"}}
```

After modifying or creating flows/nodes, **always** include navigation buttons **and** a `refreshCache` button together, and tell the user to click it (or do a hard browser refresh) to see the changes:
```json
{"type": "button", "text": "Open flow 55", "action": "openFlow", "params": {"flowId": "55"}}
{"type": "button", "text": "Refresh to see changes", "action": "refreshCache"}
```

### Prompt suggestions

Add 2-3 prompt chips when there are natural follow-up questions:
```json
{"type": "prompt", "text": "Show me the session logs"}
{"type": "prompt", "text": "What about flow 42?"}
```

## Combined Example

```json
{
  "message": "Found **3 servers** with high CPU usage:",
  "tools": ["Build mode"],
  "ef_tables": [{
    "rows": [
      {"server": "prod-web-01", "cpu": 94.2, "status": "critical"},
      {"server": "prod-api-03", "cpu": 87.1, "status": "warning"},
      {"server": "staging-01", "cpu": 82.5, "status": "warning"}
    ],
    "isEditable": false,
    "rowsSelectionType": "select"
  }],
  "action_message": [
    {"type": "button", "action": "sendButtonTextWithParams", "text": "Restart selected", "params": {"operation": "restart"}},
    {"type": "button", "action": "processTables", "text": "Process selected rows"},
    {"type": "prompt", "text": "What about memory usage?"},
    {"type": "prompt", "text": "Show all servers"}
  ]
}
```

## Guidelines

- **Be concise.** Keep `message` focused. Don't repeat data that's already in a table.
- **Use tables for structured data.** Lists of items, sessions, nodes — put them in `ef_tables`.
- **Offer prompts.** After answering, suggest 2-3 natural follow-ups as prompt chips.
- **Navigate after changes.** When you create or modify a flow/node, include an openFlow/openNode button.
- **Minimal fields.** Don't include `ef_tables` or `action_message` if you don't need them.
