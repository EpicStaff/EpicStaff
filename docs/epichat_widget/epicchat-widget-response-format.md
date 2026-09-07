# EpicChat Widget — Response Format Reference

How to structure the flow's final output so the EpicChat widget renders it correctly.

The widget calls `convertEpicstaffResponseToEpResponse(output)` on the **last finish message's `output`** (or `status_data.variables.final_result` if present). The output is a flat JSON object; recognized top-level keys are listed below.

---

## 1. Message Text

```json
{
  "message": "Your reply here. **Markdown** is supported."
}
```

- **Key**: `message` (string)
- Rendered as the main chat bubble using **ngx-markdown** (full Markdown: headings, bold, italic, code blocks, lists, links, etc.)
- This is the **minimum required field** for a reply to appear.

---

## 2. Tables (`ef_tables`)

The widget converts `ef_tables` → internal `_tables` format automatically.

### Minimal (rows only — columns auto-detected)

```json
{
  "message": "Here are the results:",
  "ef_tables": [
    {
      "rows": [
        {"name": "Alice", "score": 95, "passed": true},
        {"name": "Bob", "score": 72, "passed": true}
      ]
    }
  ]
}
```

- Columns are inferred from the first row's keys
- Column types auto-detected: `boolean`, `number`, `date`, `text`
- Tables are **editable** and **sortable** by default
- Download buttons (CSV, XLSX) added automatically

### Full (explicit columns + options)

```json
{
  "ef_tables": [
    {
      "columns": [
        {"key": "name", "title": "Name", "visible": true, "editable": false, "type": "text"},
        {"key": "score", "title": "Score", "visible": true, "editable": true, "type": "number"}
      ],
      "rows": [
        {"name": "Alice", "score": 95}
      ],
      "id": "my-table-1",
      "isEditable": true,
      "isSortable": true,
      "defaultSortField": "score",
      "rowsSelectionType": "select",
      "preselectedRows": [0],
      "tableActions": [
        {"text": ".csv", "action": "downloadEpTableCsv", "type": "button"},
        {"text": ".xlsx", "action": "downloadEpTableExcel", "type": "button"}
      ],
      "unions": [
        {"title": "Group A", "keys": ["col1", "col2"]}
      ]
    }
  ]
}
```

### Table options

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | string | auto-generated | Unique table identifier |
| `isEditable` | boolean | `true` | Allow inline cell editing |
| `isSortable` | boolean | `true` | Allow column sorting |
| `defaultSortField` | string | first column | Initial sort column key |
| `rowsSelectionType` | `"select"` \| `"multiSelect"` \| `"edit"` | `"edit"` | Row interaction mode |
| `preselectedRows` | number[] | `[]` | Initially selected row indices |
| `selectedRowIndices` | number[] | `[]` | Currently selected rows (updated by widget) |
| `tableActions` | Action[] | CSV+XLSX buttons | Custom action buttons above the table |
| `unions` | `{title, keys}[]` | `[]` | Column grouping headers |

### Table processing

When the user clicks **"Process tables"** (`processTables` action), the widget sends the table data (including any edits and selected rows) back to the flow as `contextExtras` merged into `variables.context`.

---

## 3. Action Buttons (`action_message`)

```json
{
  "message": "What would you like to do?",
  "action_message": [
    {"type": "button", "action": "sendAction", "text": "Option A"},
    {"type": "button", "action": "sendAction", "text": "Option B"},
    {"type": "link", "action": "link", "text": "Open docs", "params": {"url": "https://example.com"}},
    {"type": "prompt", "text": "Try asking about X"}
  ]
}
```

### Action types

| `type` | Behavior |
|---|---|
| `"button"` | Rendered as clickable buttons below the message. Removed after click. |
| `"link"` | Rendered as clickable links below the message. Opens URL from `params.url`. |
| `"prompt"` | Rendered as suggestion chips in the input footer (last message only). Clicking sends the `text` as a new user message. |

### Built-in action identifiers

| `action` value | Description |
|---|---|
| `"sendAction"` | Sends `text` as `user_action` to the flow |
| `"sendButtonTextWithParams"` | Sends `text` as `user_action` + `params` as context extras |
| `"switchAgent"` | Switches to another flow. `params: {"flow_id": <flow_id>, "url": "..."}` |
| `"processTables"` | Sends edited table data back to the flow |
| `"link"` | Opens `params.url` in browser |
| `"downloadEpTableCsv"` | Downloads table as CSV |
| `"downloadEpTableExcel"` | Downloads table as XLSX |
| `"resetTable"` | Reverts table edits to original |
| `"addTokens"` | Placeholder for token purchase (not implemented) |
| `"openFlow"` | Emits app event to open flow designer. `params: {"flowId": <flow_id>}` |
| `"openNode"` | Emits app event to open a specific node. `params: {"flowId": <flow_id>, "nodeId": "<node_uuid>"}` |
| `"refreshCache"` | Emits app event to refresh frontend cache |

### Button sequencing

Multiple buttons with sequential order appear in the same row. Buttons are removed from the message after the user clicks one.

---

## 4. Combined Example

```json
{
  "message": "I found **3 servers** with high CPU usage:",
  "ef_tables": [
    {
      "rows": [
        {"server": "prod-web-01", "cpu": 94.2, "status": "critical"},
        {"server": "prod-api-03", "cpu": 87.1, "status": "warning"},
        {"server": "staging-01", "cpu": 82.5, "status": "warning"}
      ],
      "isEditable": false,
      "rowsSelectionType": "select"
    }
  ],
  "action_message": [
    {"type": "button", "action": "sendButtonTextWithParams", "text": "Restart selected", "params": {"operation": "restart"}},
    {"type": "button", "action": "sendAction", "text": "Show details"},
    {"type": "prompt", "text": "What about memory usage?"}
  ]
}
```

---

## 5. Request Payload (what the flow receives)

When the user sends a message or clicks an action, the widget sends a `context` object:

```json
{
    "context": {
        "user_input": "create a new flow",
        "chat_history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello! How can I help?"}
        ],
        "tools": "Build mode",
        "web": {"mode": "all"},
        "chat_session_id": 1773075355088,
        "page_url": "http://localhost:4200/flows/3"
    }
}
```

### Context fields

| Field | Type | Description |
|---|---|---|
| `user_input` | string | User's text message |
| `user_action` | string | Action text when button clicked (instead of `user_input`) |
| `chat_history` | `{role, content}[]` | Previous messages in the conversation |
| `tools` | string \| null | Name of the currently selected tool (e.g. `"Build mode"`), or absent if none selected |
| `web` | object \| null | Web search config if enabled: `{"mode": "all" \| "restrict" \| "prioritize"}` |
| `chat_session_id` | number | Persistent widget session ID (timestamp-based) |
| `page_url` | string | Current browser URL — useful for detecting which flow the user is viewing |
| `user_params` | object | From widget's `userData` attribute |

Action-specific context extras (e.g., edited table data from `processTables`) are merged directly into `context`.

### Build mode

Build mode is activated via the **tools dropdown** in the widget. When the agent includes `"Build mode"` in the `tools` response field, the user can select it from the dropdown. While selected, `"tools": "Build mode"` is sent in every message context.

The flow/agent should check `context.tools == "Build mode"` to decide whether to plan-only or execute changes directly.

The first time a session starts, the agent can offer build mode via a button:
```json
{
    "message": "I can help you build flows. Want me to make changes directly?",
    "action_message": [
        {"type": "button", "action": "sendAction", "text": "Allow build mode"}
    ]
}
```

Or simply include it in `tools` so the user can toggle it from the dropdown at any time.

---

## 6. Agent Response Capabilities

The agent can declare UI capabilities in its response. These persist across messages as long as the agent keeps sending them.

```json
{
    "message": "Here's what I found...",
    "tools": ["Build mode", "Deep research"],
    "allow_files": true,
    "allow_web": true
}
```

### Capability fields

| Field | Type | Description |
|---|---|---|
| `tools` | string[] | Tool/mode toggles shown in the input area. The selected tool stays active across messages if the next response also includes it. |
| `allow_files` | boolean | If `true`, shows a paperclip icon — user can attach files. |
| `allow_web` | boolean | If `true`, shows web search options: no web / all web / restrict / prioritize. Selected option is sent back in context. |

### Tool toggles

Tools are rendered as a dropdown in the input area. The user selects one (or "None"). The selected tool name is sent as `context.tools` (string) in every subsequent message.

If the next agent response no longer includes the selected tool in its `tools` array, the selection is automatically cleared.

Example flow:
1. Agent responds: `"tools": ["Build mode", "Deep research"]`
2. User selects "Build mode" from dropdown
3. Next user message includes `"tools": "Build mode"` in context
4. Agent responds again with `"tools": ["Build mode", "Deep research"]` → selection persists
5. Agent responds without `tools` or without "Build mode" → selection cleared

---

## 7. Streaming Messages

During execution, the widget displays streaming messages in a **"Thinking..." expander**.

### Recognized stream message types

| `message_type` | Source | Displayed in Thinking |
|---|---|---|
| `python_stream` | Python node | ✅ |
| `agent_node_stream` | AgentNode | ✅ |
| `task_node_stream` | TaskNode | ✅ |

> `crewai_output` and `code_agent_stream` are both gone — the Crew node and the
> Code Agent node were removed and no backend service emits either any more.
> `AgentNode` / `TaskNode` emit `agent_node_stream` / `task_node_stream`
> instead (see
> [../agent_and_task_node/Session_Messages.md](../agent_and_task_node/Session_Messages.md)).

`python_stream` messages carry the text inline:
```json
{
  "message_type": "python_stream",
  "text": "Working on your request...",
  "is_final": false
}
```

Node-stream messages use a different envelope — the payload lives in `data`,
keyed by `event` (`task_start`, `tool_call`, `tool_result`, `task_finish`),
with no flat `text` field:
```json
{
  "message_type": "agent_node_stream",
  "event": "task_finish",
  "step_id": 3,
  "is_final": false,
  "data": { "message": "Done." }
}
```

### No per-message filtering

There is no way to hide individual stream messages any more. The `sse_visible`
field, the per-node `stream_config` checkboxes (including `final_reply`), and
the filtered SSE endpoint (`run-session/subscribe/<id>/filtered/`) were all
removed. Every node that streams now streams everything to the single
`run-session/subscribe/<id>/` endpoint.

---

## 8. Widget Input Behavior

| Feature | Behavior |
|---|---|
| **Shift-Enter** | Inserts a newline in the input field |
| **Ctrl-Z** | Undo in the input field |
| **Up arrow** | Does NOT recall previous message (disabled) |
| **Click outside** | Does NOT hide the chat panel |

---

## 9. CSS Custom Properties

The widget exposes CSS custom properties for theming. Set them on the `<epicstaff-chat>` element.

| Property | Description |
|---|---|
| `--ep-color-surface` | Main background |
| `--ep-color-surface-alt` | Alternate background (e.g. answer bubbles) |
| `--ep-chat-bg-question` | User message bubble background |
| `--ep-chat-bg-answer` | Agent message bubble background |
| `--ep-color-text` | Primary text color |
| `--ep-color-text-muted` | Secondary text color |
| `--ep-color-border` | Border color |
| `--ep-color-accent` | Accent / link color |
| `--ep-color-shadow` | Shadow color |
| `--ep-color-scrollbar` | Scrollbar thumb color |
| `--ep-color-disabled-bg` | Disabled element background |
| `--ep-color-danger-soft` | Soft danger/accent color |
