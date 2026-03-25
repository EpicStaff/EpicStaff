# Code Agent & EpicChat

Read this when setting up, configuring, or debugging Code Agent nodes and EpicChat integration.

## Code Agent Overview

The Code Agent node replaces manual OpenCode management with a single configurable node. The "code" container runs an Instance Manager (port 4080) that spawns OpenCode instances on demand per LLM config.

- **API endpoint**: `code-agent-nodes/` — standard CRUD
- **Key fields**: `llm_config` (FK), `agent_mode` (build/plan), `system_prompt`, `stream_handler_code`, `libraries`, timeout settings, `input_map`, `output_variable_path`, `output_schema`
- **Runtime**: `CodeAgentNode` handles instance allocation, prompt submission, streaming, cleanup
- **Stream handler**: User-provided Python callbacks (`on_stream_start`, `on_chunk`, `on_complete`)
- **CLI**: `create-code-agent-node` creates DB record + metadata in one command

## EpicChat Structured Output

Code Agent nodes can return structured JSON to the EpicChat widget instead of plain text, enabling rich responses with markdown, tables, action buttons, links, and suggestion chips.

**How it works:**
1. Set `output_schema` on the Code Agent node (JSON schema describing the response format)
2. Runtime sends the schema to OpenCode as `format: {type: "json_schema", schema: ...}`
3. OpenCode returns validated JSON in the `structured` field
4. EpicChat renders using the schema's structure (message, tables, buttons, etc.)

**Reference schema:** `docs/epicchat-response.schema.json` — the frontend pre-populates new Code Agent nodes with this schema.

**Key schema fields:**
- `message` (string) — main response text (supports markdown)
- `ef_tables` (array) — structured data tables
- `action_message` (array) — interactive elements: buttons, links, prompt suggestions

## EpicChat Actions: `user_input` vs `user_action`

EpicChat sends different context fields depending on how the user interacts:

| Field | When | Semantics |
|---|---|---|
| `context.user_input` | User types a message or clicks a `prompt` suggestion | Conversational — "the user said this" |
| `context.user_action` | User clicks a `button` with `action: "sendAction"` | Programmatic — "the user clicked this" |

The Code Agent's `input_map` must include both:
```json
{
  "prompt": "variables.context.user_input",
  "action": "variables.context.user_action"
}
```

If only `prompt` is mapped, button clicks crash with `AttributeError: 'DotDict' object has no attribute 'user_input'`. The runtime uses `set_missing_variables=True` so whichever field is absent gets `"not found"` instead of crashing.

**Runtime resolution in `execute()`:**
- `prompt` has text → used as the agent prompt (normal message)
- Only `action` has text → action text becomes the prompt
- `action` matches a build trigger → mode switches to `build`

## Build Mode Pattern

Code Agent nodes run in their configured `agent_mode` (usually `plan` — read-only). To allow file edits, the agent needs `build` mode. Use the build permission pattern:

1. Configure the node with `agent_mode=plan` (safe default)
2. Agent proposes a plan, returns a button:
   ```json
   {
     "message": "Here's my plan: ...",
     "action_message": [
       {"type": "button", "text": "Allow build mode (3 turns)", "action": "sendAction"}
     ]
   }
   ```
3. User clicks → EpicChat sends `user_action: "Allow build mode (3 turns)"`
4. Code Agent detects the trigger, overrides `agent_mode` to `"build"`
5. Agent executes in build mode; remaining turns carry over

**Option buttons** — for multiple approaches, append ` - <label>`:
```json
{"type": "button", "text": "Allow build mode (3 turns) - Fix existing code", "action": "sendAction"}
{"type": "button", "text": "Allow build mode (3 turns) - Rewrite from scratch", "action": "sendAction"}
```
The backend extracts the label and forwards it as context.

**Trigger format:** `"Allow build mode"` (1 turn), `"Allow build mode (N turns)"`, or `"Allow build mode (N turns) - <option>"`. Case-insensitive.

## EpicChat Setup Steps

1. PATCH `input_map` to include both `prompt` and `action` (see above)
2. Set `output_schema` (UI Output Schema tab or API PATCH; default: `docs/epicchat-response.schema.json`)
3. Configure start node variables: `context: {}` (populated by EpicChat at runtime), `result: {}` (written by Code Agent output)
