# AgentNode & TaskNode — Session Messages

How AgentNode and TaskNode report execution to the client during a graph/flow
run. Both are normal graph nodes streamed over the session SSE connection as
`event: messages`. Branch on `message_data.message_type`.

- **AgentNode** (`src/crew/services/graph/nodes/agent_node.py`) runs one agent
  over an **ordered list of sub-tasks** (`AgentNodeTask`), dispatched to the
  agent service as `RunType.LIST_OF_TASKS`.
- **TaskNode** (`src/crew/services/graph/nodes/task_node.py`) runs one agent
  over a **single task**, dispatched as `RunType.SINGLE_TASK`.

Producers: `agent_node.py` / `task_node.py` (stream events) and the shared
`BaseNode.run` (`start`/`finish`/`error`). Envelope model:
`src/crew/models/graph_models.py` (`GraphMessage`). Transport details (Redis
channels, SSE endpoint) live in the general session-messages reference; this doc
covers only these two nodes.

## Envelope

Every `messages` event's `data` is:

```jsonc
{
  "session_id": 123,          // Session PK
  "name": "agentnode_5",      // emitting node's name
  "execution_order": 7,       // monotonic per-run counter — order the timeline by this
  "timestamp": "2026-07-07T10:56:54.045Z", // ISO-8601 UTC, ms precision
  "uuid": "…",                // unique per message — use as key / dedupe id
  "message_data": { "message_type": "…", /* type-specific fields below */ }
}
```

## AgentNode vs TaskNode — the only differences

|                         | AgentNode                                            | TaskNode                          |
|-------------------------|------------------------------------------------------|-----------------------------------|
| stream `message_type`   | `agent_node_stream`                                  | `task_node_stream`                |
| sub-tasks               | 1..N ordered tasks; stream events carry `data.task`  | single task; **no** `data.task`   |
| `finish.output`         | aggregated (last task's text, summed totals)         | the single task's result          |

Lifecycle, `finish`/`error` shape, `stop_reason`, and `token_usage` are
identical between them.

## Message types

### `start`
```jsonc
{ "message_type": "start", "input": <mapped input> }
```
Node began; `input` is the node's mapped input.

### Live tool activity — `agent_node_stream` / `task_node_stream` (0..N)
```jsonc
{
  "message_type": "agent_node_stream",   // or "task_node_stream"
  "event": "tool_call" | "tool_result",
  "step_id": 3,            // monotonic within this node execution
  "is_final": false,       // always false for these
  "sse_visible": true,
  "data": {
    // event = "tool_call":   { id, name, arguments, truncated, token_usage }
    // event = "tool_result": { tool_call_id, name, content, is_error, truncated, token_usage }
    "task": { "name": "Task 2", "order": 1 }   // AgentNode multi-task only; absent for TaskNode / single-task
  }
}
```
Streamed as the agent calls tools. `data` is the raw agent-service event
payload. For a multi-task AgentNode, `data.task` attributes the call to a
sub-task — **guard for it being absent**.

### `finish`
```jsonc
{
  "message_type": "finish",
  "output": {
    "message": "…final text…",   // AgentNode: last task's text. TaskNode: the task's answer.
    "stop_reason": "completed",  // completed | max_iter_reached | schema_satisfied | max_consecutive_failures
    "iterations": 2,             // AgentNode: summed across sub-tasks
    "tool_invocations": 0,       // AgentNode: summed across sub-tasks
    "token_usage": { "prompt_tokens": 95, "completion_tokens": 55, "total_tokens": 150 }
  },
  "state": { "variables": {…}, "state_history": [...] },
  "additional_data": null,
  "sse_visible": true            // false when the node is configured hidden
}
```
Node completed successfully. `output.message` is what you render.

### `error`
```jsonc
{ "message_type": "error", "details": "…error message…" }
```
The run failed (LLM error, timeout, or an output schema that could not be
satisfied) — the node raised.

## `stop_reason` values (in `finish.output`)

| value | meaning |
|---|---|
| `completed` | Normal completion — the agent returned a final answer and stopped calling tools. |
| `schema_satisfied` | The task had an `output_schema`; `message` is a JSON string matching it. |
| `max_iter_reached` | Hit the tool-turn cap (`max_iter`). Partial result. |
| `max_consecutive_failures` | Hit the consecutive tool-failure cap (`max_consecutive_failures`). Agent produced a graceful summary. Partial result. |

> ⚠️ `completed` **replaced the legacy value `no_tool_calls`**. Update any FE
> code keyed on `no_tool_calls`.

Hard failures (`llm_error`, `timeout`) do **not** appear here — they arrive as an
`error` message instead of `finish`.

## Handling rules

- **Lifecycle:** exactly one `start`, then 0..N stream events, then one `finish`
  **or** one `error`.
- **Order** the timeline by `execution_order`, then `timestamp`; **dedupe** by
  `uuid` (history replay on connect can overlap live events).
- **AgentNode multi-task:** group `agent_node_stream` events by
  `data.task.order` / `data.task.name` for per-sub-task display. `finish.output`
  is the aggregate.
- **`sse_visible: false`** on `finish` → do not render in user-facing chat.
- **Unknown `message_type`:** ignore gracefully — new types may be added.

## Related

- `src/shared/models/agent_service.py` — `StopReason` enum (source of truth for
  the `stop_reason` values above).
- General session-messages reference — all other node/graph/status message types
  and the Redis/SSE transport.
