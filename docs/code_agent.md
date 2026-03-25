# Code Agent Node

## What Is It?

The **Code Agent** is a flow node that gives your flow access to an AI coding agent (OpenCode). You configure it with an LLM, a system prompt, and optional streaming callbacks — the node handles everything else: session management, polling, streaming, and timeout handling.

Use it when you need a flow to:
- Run an autonomous coding agent that can execute commands, read/write files
- Stream real-time progress (reasoning + tool calls) to external platforms (Google Chat, Telegram, etc.)
- Maintain persistent conversations across multiple flow triggers (same `chat_id` = same session)

---

## Quick Start

1. **Add a Code Agent node** to your flow in the visual editor
2. **Select an LLM Config** (provider + model + API key — configured in Settings)
3. **Write a System Prompt** — tells the agent what it should do
4. **Wire the input_map** — at minimum, map `prompt` from an upstream variable
5. **Optionally write Stream Handler callbacks** — deliver output to external platforms

### Minimal Example

```
[__start__] → [Code Agent]
```

1. Set start node variables: `{"prompt": "Build me a hello world app", "chat_id": "test_1"}`
2. Code Agent input_map: `{"prompt": "variables.prompt", "chat_id": "variables.chat_id"}`
3. Run the flow — the agent receives the prompt, works, and returns `{reply, session_id}`

For external integrations (Google Chat, Telegram), add upstream nodes that parse the webhook payload and downstream nodes that deliver the reply.

---

## Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| **LLM Config** | dropdown | required | Which LLM to use (provider + model + API key) |
| **Agent Mode** | `build` / `plan` | `build` | OpenCode agent mode |
| **System Prompt** | text area | empty | Instructions for the agent (applied once when session is created) |
| **Stream Handler Code** | code editor | empty | Python callbacks for real-time output delivery |
| **Libraries** | list | empty | pip packages needed by the stream handler |
| **Polling Interval** | ms | `1000` | How often to check for new content |
| **Chunk Timeout** | seconds | `30` | Max wait for first response (skipped while agent is busy) |
| **Inactivity Timeout** | seconds | `120` | Max silence before aborting |
| **Max Wait** | seconds | `300` | Absolute maximum execution time |

---

## Inputs & Outputs

### Inputs (via input_map)

| Input | Required | Description |
|---|---|---|
| `prompt` | yes | The user message to send to the agent |
| `chat_id` | no | Logical key for session reuse (e.g., `telegram_12345`). Same `chat_id` = same conversation |
| *(any)* | no | Additional values passed through to stream handler `context` |

### Outputs (via output_variable_path)

| Output | Description |
|---|---|
| `reply` | Full text of the agent's final response |
| `session_id` | OpenCode session ID (for downstream reuse or debugging) |

---

## Stream Handler

The stream handler is optional Python code with three callbacks that deliver output to external platforms in real-time:

```python
def on_stream_start(context):
    """Called before the prompt is sent to the agent.
    Use this to set up the output channel (e.g., send a 'thinking' bubble).
    """
    pass

def on_chunk(text, context):
    """Called whenever new content arrives (reasoning + tool call summaries).
    Text accumulates — each call contains the full content so far.
    """
    pass

def on_complete(full_reply, context):
    """Called when the agent finishes responding.
    Use for final message formatting, cleanup, etc.
    """
    pass
```

The `context` dict contains all values from your **input_map** plus `session_id` and `node_name`. This gives the handler access to upstream data like `service_account_info`, `chat_id`, `bot_token`, etc.

### Example: Google Chat Streaming

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/chat.bot"]

def on_chunk(text, context):
    msg_id = context.get("thinking_message_id")
    sa_info = context.get("gchat_service_account_info")
    if not msg_id or not sa_info:
        return
    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    chat = build("chat", "v1", credentials=creds)
    display = text[-2000:] if len(text) > 2000 else text
    chat.spaces().messages().patch(
        name=msg_id, updateMask="text", body={"text": f"> Reasoning...\n{display}"}
    ).execute()

def on_complete(full_reply, context):
    msg_id = context.get("thinking_message_id")
    sa_info = context.get("gchat_service_account_info")
    if msg_id and sa_info:
        creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
        chat = build("chat", "v1", credentials=creds)
        chat.spaces().messages().patch(
            name=msg_id, updateMask="text", body={"text": full_reply or "No response."}
        ).execute()
```

Libraries needed: `google-auth`, `google-api-python-client`

---

## Session Management

- **New session** — created automatically when `chat_id` hasn't been seen before
- **Reuse session** — same `chat_id` reuses the existing OpenCode session (persistent conversation)
- **System prompt** — injected once at session creation, along with runtime context (flow ID, node name, anti-recursion warning)
- **Session persistence** — sessions survive instance restarts (stored in SQLite)

---

## What You See During Execution

The thinking bubble / session stream shows:
- **Reasoning** — the agent's thought process as it works
- **Tool calls** — commands and file operations the agent executes (e.g., `[bash] ls -la`)
- **Final answer** — the completed response

Session messages include both the streaming text and structured `tool_calls` data:

```json
{
    "message_type": "code_agent_stream",
    "text": "reasoning + tool summaries...",
    "tool_calls": [
        {"name": "bash", "input": "ls -la", "output": "...", "state": "completed"}
    ],
    "is_final": false
}
```

---
---

# Developer Reference

## Architecture

### "code" Container

A dedicated Docker container that hosts OpenCode instances.

| Component | Description |
|---|---|
| **Instance Manager** | Python HTTP service (port 4080) that spawns/manages OpenCode instances |
| **OpenCode instances** | One per LLM config, each on its own port (4096+N) with isolated HOME directory |
| **Skill files** | Baked into image, synced to `savefiles/.opencode/skills/` at startup |
| **Shared volume** | `savefiles/` volume (via `CREW_SAVEFILES_PATH`) |
| **Network** | `backend-network` — needs `django_app`, `redis` |

### Instance Manager

Entry point for the "code" container:

1. Listens on port **4080** for instance requests
2. Spawns OpenCode instances on demand (one per `llm_config_id`)
3. Each instance gets its own port, HOME directory, env vars, and `opencode.json`
4. Reaps idle instances after configurable timeout (default: 5 minutes)

```
GET  /instance/{llm_config_id}       → { "port": 4097, "status": "ready" }
GET  /instances                       → list all running instances
POST /instance/{llm_config_id}/stop  → stop a specific instance
GET  /health                          → manager health check
```

**Instance isolation:**

```
/opt/opencode/instances/{llm_config_id}/
├── .config/opencode/opencode.json   # provider + model config
├── .local/share/opencode/           # SQLite DB, sessions, auth
└── log/
```

**LLM config flow:**

```
Request for llm_config_id=5
  → Check: instance already running?
      YES → return port, update last_used
      NO  →
        1. GET http://django_app:8000/api/llm-configs/5/
           → {provider: "anthropic", model_name: "claude-sonnet-4-20250514", api_key: "sk-..."}
        2. Create HOME dir, write opencode.json with provider config
        3. Export ANTHROPIC_API_KEY=sk-...
        4. Spawn: opencode serve --port {next_port} --hostname 0.0.0.0
        5. Wait for health check
        6. Return port
```

**Idle reaping:**

- Instances unused for >5 minutes (configurable via `CODE_IDLE_TIMEOUT`) are killed
- Sessions persist in SQLite — restarting the same config recovers history
- Maximum concurrent instances capped (configurable via `CODE_MAX_INSTANCES`, default: 5)

---

## Runtime Engine

The node's execute method (system-managed, not visible to users):

1. **Resolves LLM config** — fetches provider/model/key from Django API
2. **Gets OpenCode instance** — calls Instance Manager to get/create instance for this config
3. **Manages session** — creates or reuses OpenCode session (keyed by `chat_id` from input_map)
4. **Injects runtime context** — on first message in a new session, prepends `graph_id`, `node_name`, and anti-recursion warning so the agent knows its own identity and avoids triggering its own flow
5. **Applies system prompt** — appended after runtime context on first message
6. **Calls `on_stream_start`** — before sending the prompt
7. **Sends prompt** — `POST /session/{sid}/message` in a **background thread** so polling starts immediately
8. **Poll loop** (busy-aware):
   - Checks `POST` error — exits immediately if the send failed
   - Checks OpenCode `/session/status` — determines if session is busy or idle
   - Polls `/session/{sid}/message` for new messages at configured interval
   - Detects `reasoning` parts → streams via `on_chunk` and `StreamWriter`
   - Detects `tool` / `step-start` parts → resets activity timer (agent is working)
   - Detects `text` part → final answer, exits loop
   - **Timeouts only trigger when OpenCode is NOT busy**: chunk timeout (no response started), inactivity timeout (no new content)
   - On silence > threshold: emits `text + "..."` via `on_chunk`
   - On OpenCode idle → final fetch and exit
9. **Calls `on_complete`** — when OpenCode finishes
10. **Returns output** — `{reply, session_id}`

---

## Session Streaming

The Code Agent node streams to **two independent channels**:

### 1. Session Stream (automatic, via LangGraph StreamWriter)

Every poll emits a `GraphMessage` via `StreamWriter` → Redis `graph:messages` → frontend session view.

### 2. Platform Callback (user-coded, via stream handler)

The `on_chunk` / `on_complete` callbacks deliver output to external platforms. Independent of the session stream, runs in parallel via the sandbox code executor.

---

## DB Model

### Django Model: `CodeAgentNode`

```python
class CodeAgentNode(models.Model):
    graph = models.ForeignKey(Graph, on_delete=models.CASCADE)
    node_name = models.CharField(max_length=255)
    llm_config = models.ForeignKey(LLMConfig, on_delete=models.SET_NULL, null=True)
    agent_mode = models.CharField(max_length=10, default="build")  # build | plan
    system_prompt = models.TextField(blank=True, default="")
    stream_handler_code = models.TextField(blank=True, default="")
    libraries = models.JSONField(default=list)  # pip packages for stream handler
    polling_interval_ms = models.IntegerField(default=1000)
    silence_indicator_s = models.IntegerField(default=3)
    indicator_repeat_s = models.IntegerField(default=5)
    chunk_timeout_s = models.IntegerField(default=30)
    inactivity_timeout_s = models.IntegerField(default=120)
    max_wait_s = models.IntegerField(default=300)
    input_map = models.JSONField(default=dict)
    output_variable_path = models.CharField(max_length=255, blank=True, default="")
```

### API Endpoints

Standard CRUD following the existing pattern for node types:
- `GET/POST /api/graphs/{graph_id}/code-agent-nodes/`
- `GET/PATCH/DELETE /api/code-agent-nodes/{id}/`

### GraphData Schema

`code_agent_node_list` in `GraphData` (`request_models.py`) — serialized to Redis for crew consumption.

---

## Docker Compose

```yaml
code:
  image: code
  build:
    context: .
    dockerfile: ./code/Dockerfile.code
  container_name: code
  environment:
    - REDIS_HOST=${REDIS_HOST}
    - REDIS_PORT=${REDIS_PORT:-6379}
    - REDIS_PASSWORD=${REDIS_PASSWORD}
    - CODE_IDLE_TIMEOUT=${CODE_IDLE_TIMEOUT:-300}
    - CODE_MAX_INSTANCES=${CODE_MAX_INSTANCES:-5}
  volumes:
    - ${CREW_SAVEFILES_PATH}:${CONTAINER_SAVEFILES_PATH}
  extra_hosts:
    - "host.docker.internal:host-gateway"
  networks:
    - backend-network
  depends_on:
    - redis
```

---

## Implementation Order

1. Create "code" container with Instance Manager
2. Add `CodeAgentNode` Django model + migrations + API
3. Add `CodeAgentNode` to crew's `graph_builder.py` + runtime
4. Add frontend UI component (settings panel + stream handler editor)
