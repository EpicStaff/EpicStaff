# EpicChat: Output Standardization & Streaming

## Problem

### 1. No Standard Node Output Contract

Each node type returns a different structure:

| Node Type | Output |
|---|---|
| Code Agent | `{"reply": "...", "session_id": "..."}` |
| Crew (no Pydantic) | `{"raw": "..."}` |
| Crew (with Pydantic) | Arbitrary Pydantic model |
| Python | Whatever `main()` returns |

The EpicChat widget renders `response.message` — a field none of the nodes produce.
The sessions UI renders raw JSON — works with anything but has no semantic understanding.

Result: **EpicChat shows nothing** because it can't find `message` in the output.

### 2. No Streaming in EpicChat

The widget receives all SSE events but only acts on two:
- `message_type: "finish"` → captures `messageData.output`
- `event: "status"`, `status: "end"` → resolves the promise, displays result

Intermediate streaming messages (`code_agent_stream`, crew agent progress) are logged to console and discarded. The user sees a loading spinner until the session ends.

### 3. SSE Origin Mismatch

The widget uses `EventSource` with `withCredentials: true`. If the page origin (`http://localhost`) differs from the agent URL (`http://127.0.0.1`), the browser blocks the SSE connection. This is a configuration issue — agent URL must match the page origin.

---

## Solution

### Phase 1: Output Standardization (backend)

Define a convention: **every node that produces user-visible text must include a `message` field in its output.**

Changes:
- **Code Agent** (`code_agent_node.py` line 519): return `{"message": reply_text, "reply": reply_text, "session_id": oc_session_id}`
- **Crew node** (`crew_node.py` line 93): include `"message": crew_output.raw` alongside existing fields
- **Python node**: document the convention — `main()` should return `{"message": "..."}` for EpicChat-visible flows
- **Sessions UI**: unaffected — it renders raw JSON, so the extra `message` field just appears alongside existing fields

### Phase 2: Streaming in EpicChat Widget (frontend — separate repo)

> **Note:** The widget TypeScript source lives in a separate repository.
> The pre-built bundle is committed at `frontend/public/epicchat-widget/main.js`.
> All changes below must be made in the **widget TS source repo** and the bundle re-committed.

#### UX: Thinking Expander

```
┌─────────────────────────────────┐
│ ▸ Thinking... (6s)              │  ← collapsible, auto-collapses on finish
│ ┌─────────────────────────────┐ │
│ │ Reading the skill file      │ │
│ │ [bash] ls -la flows/        │ │
│ │ Analyzing flow structure    │ │
│ └─────────────────────────────┘ │
│                                 │
│ Here's what I found: the flow   │  ← final answer, always visible
│ has 3 nodes connected via...    │
└─────────────────────────────────┘
```

#### SSE Endpoint

The widget must subscribe to the **filtered** endpoint:
```
/run-session/subscribe/{sessionId}/filtered/
```
This endpoint only delivers messages where `sse_visible=true` (plus standard `start`/`finish`/`error`/`status` messages).

> **Status:** The local bundled `main.js` (`frontend/public/epicchat-widget/main.js`) already uses the `/filtered/` URL. The same change must be applied in the **widget TypeScript source** (`src/app/services/api.service.ts`) so it persists across future builds.

#### Widget Changes — `subscribeToEpicstaffSseSession`

**File:** `src/app/services/api.service.ts`

Currently the `"messages"` event listener only captures `finish` messages:

```typescript
// Current code — only captures finish:
if (isFinishMessageData(messageData)) {
    const output = extractOutputFromFinishMessage(messageData);
    parsedFinalOutput = this.parseOutputIfString(output);
}
```

**Add a streaming message handler** before the finish check. Streaming messages have `message_type` values of `code_agent_stream`, `crewai_output`, or `python_stream`:

```typescript
// 1. Add helper function in epicstaff-api.model.ts:
function isStreamMessageData(data: any): boolean {
    return ['code_agent_stream', 'crewai_output', 'python_stream'].includes(data.message_type);
}

// 2. In the "messages" event listener, add before the finish check:
if (isStreamMessageData(messageData)) {
    onStreamUpdate({
        messageType: messageData.message_type,
        text: messageData.text || '',
        toolCalls: messageData.tool_calls || [],
        isFinal: messageData.is_final || false,
        nodeName: data.name
    });
}
```

**`onStreamUpdate`** is a new callback parameter that the chat component passes in. It should update a "thinking expander" UI element in the current message bubble.

#### Stream Message Payload Reference

Messages arriving on the `"messages"` SSE event with `data.message_data`:

| Field | Type | Description |
|---|---|---|
| `message_type` | `string` | `"code_agent_stream"`, `"crewai_output"`, or `"python_stream"` |
| `text` | `string` | Reasoning / status text |
| `tool_calls` | `array` | Tool call objects `[{name, arguments}]` (Code Agent only) |
| `is_final` | `boolean` | `true` when this is the last stream chunk before finish |
| `sse_visible` | `boolean` | Always `true` on `/filtered/` endpoint (already filtered server-side) |

#### Thinking Expander UI Behavior

| Event | UI action |
|---|---|
| First stream message arrives | Show collapsible "Thinking..." section, start elapsed timer |
| `text` field present | Append/replace reasoning text in expander body |
| `tool_calls` present | Show tool badges (e.g. `[bash] ls -la`) inside expander |
| `is_final: true` | Stop timer, auto-collapse expander |
| `finish` message arrives | Display `output.message` as the main reply below the expander |

#### Stream Message Types by Node

| Node Type | `message_type` | Content fields |
|---|---|---|
| Code Agent | `code_agent_stream` | `{text, tool_calls, is_final}` |
| Crew | `crewai_output` | Agent/task progress text |
| Python | `python_stream` | `{text}` — e.g. "Executing 'do stuff'..." |

### Phase 3: Per-Node Streaming Configuration

Nodes that want to stream to EpicChat should expose checkmark options in their Flow Designer config panel. The user decides what gets streamed per node.

#### Code Agent Node

- [ ] Stream reasoning (thinking text)
- [ ] Stream tool calls (tool name + arguments)
- [ ] Stream tool results

#### Crew Node

- [ ] Stream agent activity (which agent is working)
- [ ] Stream task progress (task start/complete)
- [ ] Stream agent reasoning (LLM thinking)
- [ ] Stream tool calls

#### Python Node

- [ ] Stream execution status (emits `"Executing '<node_name>'..."` when the node starts)

#### How It Works

Nodes **always emit all messages** — the sessions UI must see everything. Each message is tagged with `"sse_visible": true/false` based on the node's `stream_config`. The **server** uses this flag to filter messages on the `/filtered/` endpoint; the widget never sees filtered-out messages.

The config is stored as a JSON field on the node model:

```python
# Example: CodeAgentNode
stream_config = JSONField(default=dict)
# {"reasoning": true, "tool_calls": true, "tool_results": false}
```

**Default behavior (opt-out):** When `stream_config` is empty (`{}`), all stream messages default to `sse_visible=True` — streaming is enabled by default. To disable specific stream types, set them explicitly to `false` (e.g. `{"reasoning": false}`).

Message flow:
1. Node emits message with `sse_visible` flag → `writer()` → Redis + DB
2. Sessions UI subscribes to `/run-session/subscribe/{id}/` → receives **all** messages (no filtering)
3. EpicChat widget subscribes to `/run-session/subscribe/{id}/filtered/` → server **always** drops messages where `sse_visible=false`
4. Standard messages (`start`, `finish`, `error`, `status`) always pass through regardless of endpoint
5. No browser-side bypass possible — filtering is enforced by `FilteredRunSessionSSEView`, a subclass of `RunSessionSSEView` with `_sse_filter_enabled = True`

---

## Future Work

### Auth Protection on Unfiltered Endpoint

Currently both `/subscribe/{id}/` and `/subscribe/{id}/filtered/` are unauthenticated. A user who knows the URL pattern could hit the unfiltered endpoint directly.

**Recommended fix**: Add `permission_classes = [IsAuthenticated]` to `RunSessionSSEView`. The sessions UI already has Django session auth. `FilteredRunSessionSSEView` overrides with `permission_classes = [AllowAny]` so the widget works without auth but only gets filtered data.

### Flow Designer UI for stream_config (done)

Each node panel now has a "Streaming to EpicChat" section with checkboxes:

- **Code Agent Node panel**: Reasoning, Tool calls, Tool results
- **Crew Node panel**: Agent activity, Task progress, Agent reasoning, Tool calls
- **Python Node panel**: Execution status

These map to keys in `stream_config` (e.g. `{"reasoning": true, "tool_calls": true}`). All checkboxes default to `true` (opt-out model). The save service sends `stream_config` to the backend REST API on every graph save.

### SSE CORS Fix (done)

The SSE mixin had a hardcoded `Access-Control-Allow-Origin: *` header. Combined with `EventSource(..., { withCredentials: true })`, browsers reject the connection per CORS spec (wildcard origin + credentials = network error).

**Fix:** Removed the hardcoded header from `SSEMixin`, added `CORS_ALLOW_CREDENTIALS = True` to Django settings. The `django-cors-headers` middleware now echoes back the specific `Origin` and includes `Access-Control-Allow-Credentials: true`.

---

## Widget Integration Guide

The EpicChat widget supports two integration modes depending on whether the flow needs persistent state across messages.

### Widget HTML Attributes

The `<epic-chat>` web component accepts these attributes (set by the host application):

| Attribute | Type | Description |
|---|---|---|
| `uniqueUserId` | string | Stable user identifier. Currently used **only** for local IndexedDB storage — **not sent to backend**. |
| `userData` | JSON string | Arbitrary user metadata. Parsed and sent as `variables.context.user_params` in every request. |
| `defaultAgentFlowUrl` | string | API base URL for the flow (the `agentUrl`). |
| `defaultAgentFlowId` | number | Graph/flow ID. |
| `basePath` | string | Base path for widget static assets. |
| `basicAuthLogin` / `basicAuthPassword` | string | Optional basic auth credentials. |

### What the Widget Sends Per Request

```
POST /run-session/
{
  "graph_id": <flowId>,
  "variables": {
    "context": {
      "user_input": "Hello!",
      "chat_history": [ {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."} ],
      "user_action": "...",         // optional, for action buttons
      "user_params": { ... }        // optional, from userData attribute
    }
  },
  "files": [...]                    // optional attachments
}
```

### Mode 1: Stateless (using message history)

Each user message creates a **new flow session**. No state is shared between messages. The widget sends `chat_history` (all previous messages as text) so the LLM has conversational context, but there is no persistent workspace or session identifier.

**When to use:** Simple Q&A flows, Crew tasks, any flow where each request is independent.

**Flow designer setup:**
1. Map user input: `prompt` ← `variables.context.user_input`
2. Map chat history: `chat_history` ← `variables.context.chat_history` (optional, for multi-turn context)
3. Ensure the final node output contains a `message` field for the widget to display

**Diagram:**
```
User message → POST /run-session/ (new session each time)
             → variables.context.user_input = "Hello"
             → variables.context.chat_history = [{role: "user", content: "prev msg"}, ...]
             → Flow runs → response.message displayed in widget
```

### Mode 2: Stateful (using session ID)

The widget sends a **stable session identifier** that persists across messages within the same chat. This enables nodes like the Code Agent to maintain persistent workspace state (files, edits, running processes) across multiple user messages. The session ID resets when the user clears chat history, starting a fresh workspace.

**When to use:** Code Agent flows, any flow where nodes must maintain state across messages (e.g., iterative coding, file editing, multi-step workflows).

#### Widget Change Required (for widget developer)

The widget must send a `chat_session_id` in the request payload. This ID should be:
- **Generated** when a new chat is created (e.g., `Date.now()` timestamp)
- **Persistent** across messages within the same chat
- **Reset** when chat history is cleared (`onClearChatHistory`)

**Implementation (in widget TypeScript source):**

1. Generate the ID at chat creation:
```typescript
// In chat initialization
this.chatSessionId = Date.now().toString();
```

2. Reset on clear:
```typescript
onClearChatHistory() {
    this.chatSessionId = Date.now().toString();  // new session
    // ... existing clear logic
}
```

3. Include in request payload (`sendEpicstaffRequest`):
```typescript
context2["chat_session_id"] = this.chatSessionId;
```

This makes it arrive as `variables.context.chat_session_id` in the flow.

#### Flow Designer Setup

1. Map user input: `prompt` ← `variables.context.user_input`
2. Map session ID to the Code Agent Node's `session_id` field: `variables.context.chat_session_id`
3. The Code Agent will reuse the same OpenCode session for all messages with the same `chat_session_id`

**Diagram:**
```
Chat created → chatSessionId = "1772049447807"

Message 1 → POST /run-session/ (session A)
           → variables.context.chat_session_id = "1772049447807"
           → Code Agent opens OpenCode session "1772049447807"
           → User gets response, files are created in workspace

Message 2 → POST /run-session/ (session B — new flow session, same Code Agent session)
           → variables.context.chat_session_id = "1772049447807"
           → Code Agent reuses OpenCode session "1772049447807"
           → Workspace state (files, edits) is preserved

Clear chat → chatSessionId = "1772049449123" (new timestamp)

Message 3 → POST /run-session/ (session C)
           → variables.context.chat_session_id = "1772049449123"
           → Code Agent opens fresh OpenCode session
           → Clean workspace, no previous state
```

### Summary

| | Stateless | Stateful |
|---|---|---|
| **Session per message** | New flow session each time | New flow session each time |
| **Node workspace** | Fresh each time | Persisted via `chat_session_id` |
| **Conversational context** | Via `chat_history` (text only) | Via `chat_history` + persistent workspace |
| **Widget change needed** | None | Send `chat_session_id` in payload |
| **Use case** | Q&A, Crew tasks | Code Agent, iterative workflows |
| **Chat clear behavior** | N/A | Resets `chat_session_id` → fresh workspace |
