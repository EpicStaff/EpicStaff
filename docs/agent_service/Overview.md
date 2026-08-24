# Agent Service — Overview & Runners

The **agent service** (`src/agent`) executes a single agent's work — one prompt
or an ordered list of prompts — driving a bespoke LLM tool-use loop over
**LiteLLM** (no CrewAI). It is a Redis-Streams worker: crew publishes a request,
the service runs the agent, and publishes the result back.

- **Consumers:** the crew service dispatches `TaskNode` → `SINGLE_TASK` and
  `AgentNode` → `LIST_OF_TASKS` here (`src/crew/services/agent_task_service.py`).
- **Not** a CrewAI runtime — the resolver rejects `configured-tool` / `proxy-tool`
  refs as "crew-only". Tools are called directly against the sandbox / knowledge /
  MCP services.
- FE-facing message shapes for these nodes: see
  [../agent_and_task_node/Session_Messages.md](../agent_and_task_node/Session_Messages.md).

## Transport

Redis Streams. The stream message is a **pointer**; the real payload lives at a
K/V key.

| | value | env |
|---|---|---|
| Request stream | `agent.requests` | `AGENT_REQUEST_STREAM` |
| Result stream  | `agent.results`  | `AGENT_RESULT_STREAM` |
| Consumer group | `agent-executors` | `AGENT_CONSUMER_GROUP` |

Flow: crew `SET agent:request:{correlation_id} <AgentRequest JSON>` then `XADD`
a `StreamEnvelope{type:"agent.run", correlation_id, payload:{request_key}}` to
`agent.requests`. The service reads via consumer group, hydrates the request
from the K/V key, runs it, and publishes result envelopes to `agent.results`
(`agent.result` / `agent.error`, plus live `agent.tool_call` / `agent.tool_result`
when the runner uses the tool-events emitter). Crew filters `agent.results` by
`correlation_id`.

Envelope: `shared.redis_streams.StreamEnvelope{type, correlation_id, payload}`.

## Request / response contract

Shared DTOs in `src/shared/models/agent_service.py` (single source of truth for
both services):

- **`AgentRequest`** — `correlation_id`, `run_type: RunType`,
  `agents: [AgentSpec]`, resource pools `tools: [BaseToolData]`,
  `collections: [CollectionSpec]`, `s3_files: [S3FileSpec]`, free-form
  `payload: dict`.
- **`AgentSpec`** — `id`, `name`, `instructions`, `llm`, `fcm_llm`, `max_iter`,
  `max_rpm`, `max_execution_time`, `max_retry_limit`, `default_temperature`,
  `cache`, `max_tool_calls`, `tool_timeout`, `max_consecutive_failures`, and ref
  lists `tool_refs` / `collection_refs` / `s3_refs` into the pools. A node runs
  **one** agent.
- **`AgentTaskSpec`** (LIST_OF_TASKS payload entry) — `name`, `instructions`,
  `output_schema: dict|None`, `context: [str]` (names of earlier tasks whose
  output is injected).
- **`LoopResult`** — `final_text: str|None`, `tool_invocations`, `iterations`,
  `stop_reason: str`, `token_usage: TokenUsage`, `error: str|None`.
- **`RunType`** — `SINGLE_TASK`, `LIST_OF_TASKS` (`CHAT`, `TEAM` reserved, not
  implemented).
- **`StopReason`** — `completed`, `max_iter_reached`, `schema_satisfied`,
  `llm_error`, `timeout`, `max_consecutive_failures`.
  `FAILURE_STOP_REASONS = {llm_error, timeout}` — `max_consecutive_failures` is
  a graceful stop, not a failure.

Per-`run_type` `payload` shapes:
- `SINGLE_TASK`: `{ "task_instructions": str (or "prompt"), "output_schema"?: dict }`
- `LIST_OF_TASKS`: `{ "tasks": [AgentTaskSpec, ...] }`

## Pipeline (layers)

Wired in `src/agent/main.py`; DI throughout.

```
Redis Streams (agent.requests)
  → DataLoader        # reads request_key K/V → AgentRequest        (app/data_loader.py)
  → RequestHandler    # load → build → execute → ack                (app/request_handler.py)
  → RunnerFactory     # run_type → Runner + matching Emitter        (app/factory.py)
  → Runner            # owns emitter lifecycle on_start→on_final|on_error
      → AgentResolver # AgentSpec refs → ResolvedAgent(tools, ctx)  (app/resources/resolver.py)
      → DefaultAgentLoop  # LLM tool-use loop                       (app/loop/agent_loop.py)
      → Emitter       # publishes to agent.results                  (app/emitters/)
```

`RequestHandler` always `ack`s in `finally`. On a pre-emitter failure
(load/build) it builds a fallback `RedisStreamBatchEmitter` to still publish
`agent.error`; on the happy path the runner owns the whole emitter lifecycle.

## Runners

A **Runner** owns the control flow for one `RunType`. Base ABC:
`app/runners/base.py`.

```python
class Runner(ABC):
    run_type: ClassVar[RunType]        # which RunType this handles
    emitter_mode: ClassVar[EmitterMode] # which Emitter the factory pairs
    def __init__(self, deps: RunnerDependencies): ...   # resolver + loop
    async def execute(self, request, emitter) -> None: ...
    def _select_agent(self, request) -> AgentSpec       # shared: one agent per node
```

Contract: `execute` must call `on_start` first and exactly one of `on_final`
(success) or `on_error` (failure), and must **never re-raise** — a failure is a
published `agent.error`, not an exception.

`RunnerDependencies` (`app/runners/deps.py`): frozen `{resolver, loop}`, shared
across runners. Add collaborators here if a new runner needs them.

### `SingleTaskRunner` — `RunType.SINGLE_TASK`
`app/runners/single_task.py`. `emitter_mode = TOOL_EVENTS`.
1. `on_start` → select agent → parse `task_instructions` / `output_schema`.
2. Resolve agent (tools + attachments), build prompt via
   `SingleTaskPromptBuilder`, seed the `AgentContext`.
3. `run_task_through_loop(...)` → one `LoopResult`.
4. `on_final(result)`. Domain/unexpected errors → `on_error`.

### `ListOfTasksRunner` — `RunType.LIST_OF_TASKS`
`app/runners/list_of_tasks.py`. `emitter_mode = TOOL_EVENTS`. Runs one agent
over an ordered list of `AgentTaskSpec`.
1. `on_start` → select agent → parse `payload["tasks"]` (non-empty, unique
   names).
2. **Resolve once**, reuse the `ToolRegistry` + attachments for every task.
3. For each task, in order:
   - `emitter.on_task_start(task.name, task.order)` (labels live tool events).
   - Prepend prior outputs named in `task.context` via
     `format_context_preamble` (raises if a named task hasn't run;
     block-delimited `===== PREVIOUS TASKS OUTPUTS =====`).
   - Fresh `AgentContext` per task (tasks don't share LLM history), build prompt,
     `run_task_through_loop(...)`.
   - If the task's `stop_reason` is a failure → raise → whole node aborts to
     `on_error`.
4. Aggregate into one `LoopResult`: `final_text` = **last** task's text;
   `iterations` / `tool_invocations` / `token_usage` **summed**; `stop_reason` =
   last task's. `on_final(aggregate)`.

### Shared task execution
`app/runners/task_execution.py` → `run_task_through_loop(deps, agent, context,
tools, output_schema, emitter)`. Both runners use it:
- `output_schema` **and no tools** → skip the plain loop, go straight to the
  `StructuredOutputEnforcer` (`iterations=1`, `stop_reason="schema_satisfied"`).
- otherwise run the plain loop; if it failed while a schema was requested, raise;
  if a schema was requested and the loop succeeded, enforce it and fold the
  enforcer's token usage into the result.

## The agent loop

`DefaultAgentLoop` (`app/loop/agent_loop.py`). One **iteration** = one streamed
LLM call + executing any tool calls it requested (tool errors are fed back as
`ToolResult(is_error=True)`, never abort the loop). After each iteration the
`StopPolicy` decides whether to continue.

- **`MaxIterAndNoToolCalls`** (`app/loop/stop_policy.py`): stop with
  `max_iter_reached` when `iterations >= max_iter`; else stop with `completed`
  when the model returned no tool calls (normal completion); else continue.
  `max_iter = agent.max_iter or AGENT_DEFAULT_MAX_ITER` (default 25). It is a
  safety ceiling on tool-use turns, not a target — a tool-less agent runs exactly
  one turn.
- **Wall clock:** `agent.max_execution_time` enforced via `asyncio.wait_for` →
  `stop_reason="timeout"` (separate from `max_iter`).
- **`max_tool_calls`:** caps how many tool calls are *executed* per iteration
  (per streamed assistant turn). Calls beyond the cap are rejected with an
  `is_error=True` result ("Tool call limit reached...") fed back to the model
  so every requested call id still gets a tool message; the loop continues.
  `None` means unlimited.
- **`tool_timeout`:** per-tool-call timeout in seconds, enforced via
  `asyncio.wait_for` around `ToolRegistry.execute`. A timeout produces an
  `is_error=True` result ("... timed out after Ns") and counts as a failure
  toward `max_consecutive_failures`. `None` means no timeout.
- **`max_consecutive_failures`:** counts consecutive *executed* tool results
  with `is_error=True`; resets to zero on any successful executed call.
  Overflow-rejected calls (from `max_tool_calls`) and calls skipped after the
  limit trips never count and never reset the counter. When the limit is hit,
  any remaining calls in the same batch are skipped (not executed), and the
  loop performs one graceful finalization: a single streamed LLM call with no
  tools available (`tool_choice` stripped from `model_config`) asking the
  model to summarize what it tried and why it failed. The result carries
  `stop_reason="max_consecutive_failures"` and `error=None` — this is a
  graceful stop, not a failure. `None` disables the check.
- LLM exceptions/timeouts are folded into `LoopResult(stop_reason="llm_error"|
  "timeout", error=...)` and signalled up — the loop does not emit `on_error`.

## Structured output

`StructuredOutputEnforcer` (`app/output/enforcer.py`) forces the model to call
the `submit_final_answer` system tool with schema-valid args, validating via
`jsonschema` and retrying up to `AGENT_SCHEMA_MAX_RETRIES` (default 2) → at most
`retries + 1` LLM calls, each with an internal `max_iter=1`. Non-object schemas
are auto-wrapped under a `result` key and unwrapped on return
(`app/output/schema.py`). On success `final_text = json.dumps(parsed)`,
`stop_reason="schema_satisfied"`; after retries fail →
`SchemaValidationError` → `on_error`. This retry budget is **independent** of
`max_iter`.

## Emitters

`app/emitters/`. The `Emitter` ABC (`base.py`) is a transport-agnostic sink;
lifecycle `on_start → (on_chunk|on_tool_call|on_tool_result|on_warning)* →
on_final|on_error`, plus an optional no-op `on_task_start(name, order)` hook for
multi-task runs.

| `EmitterMode` | class | behavior |
|---|---|---|
| `BATCH` | `RedisStreamBatchEmitter` | buffers everything, publishes one `agent.result` / `agent.error`. |
| `TOOL_EVENTS` | `RedisStreamToolEventEmitter` | batch **plus** live `agent.tool_call` / `agent.tool_result` envelopes (with token-usage deltas and, for multi-task runs, a `task` label). Used by both current runners. |
| `STREAM` | — | reserved; the factory raises `NotImplementedError`. |

The factory (`app/factory.py`) picks the emitter from the runner's
`emitter_mode`.

## Tools & resources

`AgentResolver.resolve` (`app/resources/resolver.py`) turns an `AgentSpec`'s refs
into a `ResolvedAgent{tools: ToolRegistry, context, attachments}`.
`ToolRegistryBuilder` maps refs to async executors, each calling an external
service:
- **`python-code-tool`** → `SandboxClient` (Redis pub/sub `code_exec_tasks` /
  `code_results`). Storage flags (`use_storage`, `storage_allowed_paths`,
  `storage_org_prefix`, `session_id`) ride on the tool payload.
- **collection refs** → knowledge search tools → `KnowledgeClient`
  (`knowledge:search:get` / `:response`); naive + graph strategies.
- **`mcp-tool`** → `McpToolGateway` + `FastMCPClientFactory` (direct MCP).
- **system tools** → e.g. `submit_final_answer` for structured output.

## LLM

LiteLLM via `LiteLLMClient` (`app/llm/`), streaming-only, routed through a
`RouterPool` with a `RetryPolicy`. Configured by `configure_litellm(...)` at
boot.

## Settings (env)

`src/agent/settings.py`:

| env | default | meaning |
|---|---|---|
| `AGENT_REQUEST_STREAM` / `AGENT_RESULT_STREAM` / `AGENT_CONSUMER_GROUP` | `agent.requests` / `agent.results` / `agent-executors` | streams |
| `AGENT_DEFAULT_MAX_ITER` | `25` | fallback tool-turn cap |
| `AGENT_SCHEMA_MAX_RETRIES` | `2` | structured-output correction retries |
| `AGENT_DEFAULT_MAX_RETRIES` | `5` | LLM retry policy |
| `AGENT_CONTEXT_WARNING_RATIO` | `0.8` | emit context-window warning at this fraction |
| `AGENT_DROP_UNSUPPORTED_LLM_PARAMS` | `true` | strip params a provider rejects |
| `SANDBOX_REQUEST_CHANNEL` / `SANDBOX_RESULT_CHANNEL` | `code_exec_tasks` / `code_results` | sandbox |
| `KNOWLEDGE_SEARCH_GET_CHANNEL` / `KNOWLEDGE_SEARCH_RESPONSE_CHANNEL` | `knowledge:search:get` / `:response` | knowledge |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD`, `AGENT_LOG_LEVEL` | — | infra |

## Adding a new runner

1. Add the value to `RunType` in `src/shared/models/agent_service.py` (if new).
2. Subclass `Runner` in `app/runners/`, set `run_type` + `emitter_mode`, and own
   the `on_start → on_final | on_error` lifecycle (mirror `SingleTaskRunner`).
   Reuse `run_task_through_loop` for the per-prompt loop/enforcer logic and
   `_select_agent` from the base.
3. Register it in `main.py` next to the existing
   `factory.register(RunType.X, XRunner)` calls.
4. Export it from `app/runners/__init__.py`.
5. If it needs extra collaborators, add them to `RunnerDependencies`
   (`app/runners/deps.py`).
6. Add a test mirroring `tests/runners/test_single_task_runner.py` /
   `test_list_of_tasks_runner.py`.

## Testing

Run via the repo `make` target (uses the agent service's own venv +
`PYTHONPATH`):

```bash
make agent-tests                                             # full suite
make agent-tests ARGS="tests/runners/test_list_of_tasks_runner.py -q"
```

Key suites: `tests/runners/` (runners), `tests/loop/` (loop + stop policy),
`tests/output/` (enforcer + schema), `tests/emitters/`, `tests/resources/`
(resolver), `tests/tools/`, `tests/llm/`, `tests/test_factory.py`,
`tests/test_contract.py`.
