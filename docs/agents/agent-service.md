# Agent Service (`src/agent/`)

`src/agent/` is a standalone, async Python microservice that runs **single
agents** via [LiteLLM](https://github.com/BerriAI/litellm) — a bespoke
tool-calling loop, no agent framework. It consumes work items from Redis Streams, drives a streaming
ReAct tool-calling loop, optionally enforces a JSON-Schema structured output,
and publishes results back to Redis Streams.

The whole object graph is dependency-injected and wired by hand in
[`main.py`](../../src/agent/main.py) — there is no DI framework, no FastAPI
app, and no HTTP surface. The service is a long-running consumer loop.

## 1. Overview & Entry Point

Entry point: `async def main()` in [`src/agent/main.py`](../../src/agent/main.py),
invoked via `asyncio.run(main())`. It is a **Redis Streams consumer**, not a
web server.

Startup sequence (`main()`):

1. `load_settings()` (`src/agent/settings.py`) reads env vars into a frozen
   `Settings` dataclass; `configure_litellm(settings.agent_drop_unsupported_llm_params)`
   sets `litellm.drop_params` process-wide.
2. `consumer_name = f"{socket.gethostname()}-{uuid4().hex[:8]}"` — unique per
   process, used as the Redis Streams consumer identity.
3. `RedisStreamClient` connects and calls
   `ensure_group(stream="agent.requests", group="agent-executors", start_id="0", mkstream=True)`
   (stream/group names come from settings, defaulting to `agent.requests` /
   `agent-executors`).
4. Auxiliary transport clients are started: `SandboxClient`, `KnowledgeClient`,
   and the standalone `DataLoader` (its own Redis connection, used only for
   K/V `GET`s).
5. The object graph is assembled:
   - `LiteLLMClient()` — the `LLMClient` implementation.
   - `McpToolGateway(FastMCPClientFactory())`.
   - `RunnerDependencies(resolver=AgentResolver(sandbox_client, mcp_gateway, knowledge_client), loop=DefaultAgentLoop(llm, settings.agent_context_warning_ratio))`.
   - `RunnerFactory(deps)`, with `factory.register(RunType.SINGLE_TASK, SingleTaskRunner)`
     and `factory.register(RunType.LIST_OF_TASKS, ListOfTasksRunner)`.
   - `RequestHandler(loader, factory, redis_client, result_stream, request_stream, consumer_group)`.
6. Consume loop: `client.read(streams={agent_request_stream: ">"}, group=..., consumer=consumer_name, count=10, block_ms=5000)`.
   For each message, `StreamEnvelope.from_fields(message.fields)` is parsed;
   a parse failure is logged, the message is **acked and dropped** (poison
   pill — never retried), and the loop continues. Successfully parsed
   envelopes are passed to `handler.handle(envelope, message_id, stream)`.
7. `SIGTERM`/`SIGINT` set an `asyncio.Event` (`stop`) that breaks the consume
   loop gracefully; `NotImplementedError` from `add_signal_handler` (e.g. on
   Windows) is swallowed. On shutdown, `loader`, `client`, `sandbox_client`,
   and `knowledge_client` are all closed/stopped.

## 2. Request Flow

`RequestHandler.handle` ([`src/agent/app/request_handler.py`](../../src/agent/app/request_handler.py))
is the top-level pipeline for one stream message:

```
load (DataLoader) → build (RunnerFactory) → execute (Runner) → ack (finally)
```

- Pre-runner failures (load or build) are caught and published via a
  **fallback** `RedisStreamBatchEmitter` constructed on the spot — this is the
  only place `RequestHandler` builds an emitter itself.
- Once a `(runner, emitter)` pair exists, `runner.execute(request, emitter)`
  owns the **entire** emitter lifecycle (`on_start` → `on_final` | `on_error`);
  `RequestHandler` does not touch the emitter again.
- The stream message is **acked unconditionally** in the `finally` block,
  regardless of success or failure — the agent service never redelivers a
  message once it has been read once.

`DataLoader` ([`src/agent/app/data_loader.py`](../../src/agent/app/data_loader.py))
hydrates a `StreamEnvelope` into a frozen `AgentRequest`:

- The stream envelope is treated as a **lightweight pointer**: it carries
  `envelope.payload["request_key"]`, a Redis K/V key (e.g.
  `agent:request:<id>`).
- `DataLoader.load` does a plain `GET` on that key, `json.loads`s the blob,
  then constructs `AgentRequest(correlation_id=envelope.correlation_id, **data)`
  — `correlation_id` is injected from the envelope and is **not** present in
  the stored JSON blob.
- Any missing key, JSON decode failure, or Pydantic validation failure raises
  `DataLoadError` (domain exception), which `RequestHandler` catches.

Wire format for stream messages: `StreamEnvelope{type, correlation_id, payload}`
in [`src/shared/redis_streams/envelope.py`](../../src/shared/redis_streams/envelope.py).
`to_fields()`/`from_fields()` serialize `payload` as a JSON string inside the
Redis Streams field map (Redis Streams fields are flat string k/v pairs).

## 3. Contract / Request Models

All contract DTOs live in
[`src/shared/models/agent_service.py`](../../src/shared/models/agent_service.py),
frozen Pydantic models (`ConfigDict(frozen=True)`) shared between the
producer (django_app / whichever service writes the K/V blob) and the agent
service consumer.

### `AgentRequest`

Top-level hydrated input produced by `DataLoader`.

| Field | Type | Notes |
|---|---|---|
| `correlation_id` | `str` | Injected by `DataLoader` from the envelope; not in the stored JSON. |
| `run_type` | `RunType` | Selects the `Runner` via `RunnerFactory`. |
| `agents` | `list[AgentSpec]` | Currently always exactly one is used (see `Runner._select_agent`). |
| `tools` | `list[BaseToolData]` | Resource pool; referenced by `AgentSpec.tool_refs`. |
| `collections` | `list[CollectionSpec]` | RAG resource pool; referenced by `AgentSpec.collection_refs`. |
| `s3_files` | `list[S3FileSpec]` | S3 resource pool; referenced by `AgentSpec.s3_refs`. |
| `payload` | `dict` | Run-type-specific: `task_instructions`/`prompt`/`output_schema` for `SINGLE_TASK`; `tasks` list for `LIST_OF_TASKS`. |

### `AgentSpec`

Per-agent configuration with resource references.

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | |
| `name` | `str` | |
| `instructions` | `str` | |
| `llm` | `LLMData` | Provider + model config. |
| `fcm_llm` | `LLMData \| None` | Currently unused by the loop. |
| `max_iter` | `int \| None` | `None` → `AGENT_DEFAULT_MAX_ITER` env default. |
| `schema_max_retries` | `int \| None` | Enforcer tries = `range(n + 1)`; `None` → env default. |
| `max_rpm` | `int \| None` | Forwarded to `LiteLLMClient` as `runtime_config["max_rpm"]`. |
| `max_execution_time` | `float \| None` | Wall-clock seconds; enforced via `asyncio.wait_for` in `DefaultAgentLoop.run`. |
| `cache` | `bool \| None` | |
| `max_retry_limit` | `int \| None` | Max LLM call retry attempts; `None` → client default. |
| `default_temperature` | `float \| None` | |
| `max_tool_calls` | `int \| None` | Max tool calls executed **per iteration**; `None` → unlimited. |
| `tool_timeout` | `int \| None` | Per-tool-call timeout in seconds; `None` → no timeout. |
| `max_consecutive_failures` | `int \| None` | Consecutive failed tool calls before graceful stop; `None` disables the check. |
| `tool_refs` | `list[str]` | `unique_name` values into `AgentRequest.tools`. |
| `collection_refs` | `list[str]` | `unique_name` values into `AgentRequest.collections`. |
| `s3_refs` | `list[int]` | `id` values into `AgentRequest.s3_files`. |

### Enums / result DTOs

| Type | Values / Fields |
|---|---|
| `RunType` (`str, Enum`) | `SINGLE_TASK`, `LIST_OF_TASKS`. (`CHAT`/`TEAM` are documented as reserved for future runners but are **not yet enum members**.) |
| `StopReason` (`str, Enum`) | `completed`, `max_iter_reached`, `schema_satisfied`, `llm_error`, `timeout`, `max_consecutive_failures`. |
| `FAILURE_STOP_REASONS` | `frozenset({StopReason.LLM_ERROR, StopReason.TIMEOUT})` — checked to decide whether a run counts as a hard failure. |
| `AgentTaskSpec` | `name: str`, `instructions: str`, `output_schema: dict \| None`, `context: list[str]` (names of prior tasks whose output to inject). |
| `CollectionSpec` | `unique_name`, `collection_id`, `name`, `description: str \| None`, `search_configs: list[SearchConfigEntry]` (min length 1). |
| `SearchConfigEntry` | `rag_id: int`, `rag_type: Literal["naive", "graph"]`, `search_config: RagSearchConfig`, `embedder: EmbedderData` (forward-compat only). |
| `S3FileSpec` | `id: int`, `path: str`, `metadata: dict`. |
| `ToolResult` | `tool_call_id: str`, `content: str`, `is_error: bool = False`. |
| `TokenUsage` | `prompt_tokens`, `completion_tokens`, `total_tokens`, `cached_prompt_tokens` (subset of `prompt_tokens`, informational only), `total_cost_usd` (display-only, best-effort). |
| `LoopResult` | `final_text: str \| None`, `tool_invocations: int`, `iterations: int`, `stop_reason: str`, `token_usage: TokenUsage`, `error: str \| None`, `tasks: list[TaskRunSummary] \| None` (populated only for `LIST_OF_TASKS`). |
| `TaskRunSummary` | `name`, `order`, `final_text: str \| None`, `token_usage`, `iterations`, `tool_invocations`, `stop_reason: str \| None`. |
| `ContextAttachment` | `role: Literal["system", "user"]`, `content: str`, `source: str` — a message injected before the first LLM call. |

## 4. Runner Modes

`Runner` ABC ([`src/agent/app/runners/base.py`](../../src/agent/app/runners/base.py)):

- Class-level `run_type: ClassVar[RunType]` and `emitter_mode: ClassVar[EmitterMode]`
  are read by `RunnerFactory`. Both current runners declare
  `emitter_mode = EmitterMode.TOOL_EVENTS`.
- Constructor takes `RunnerDependencies` (resolver + loop).
- `_select_agent(request)` is shared: both runners operate on **exactly one**
  agent — if `request.agents` has more than one, the first is used and a
  warning is logged; an empty list raises `AgentServiceError`.
- Subclasses own the full emitter lifecycle: `on_start` → `on_final` | `on_error`.

`SingleTaskRunner` ([`src/agent/app/runners/single_task.py`](../../src/agent/app/runners/single_task.py)):
`run_type = RunType.SINGLE_TASK`. Parses `payload["task_instructions"]` (or
`payload["prompt"]` as fallback) plus optional `payload["output_schema"]`
(`_parse_payload` raises `AgentServiceError` if neither instructions field is
present), resolves the agent via `AgentResolver.resolve`, builds the initial
messages via `SingleTaskPromptBuilder`, runs `run_task_through_loop`, and
calls `emitter.on_final`. `AgentServiceError` and any other `Exception` are
both caught and routed to `emitter.on_error` — neither is re-raised.

`ListOfTasksRunner` ([`src/agent/app/runners/list_of_tasks.py`](../../src/agent/app/runners/list_of_tasks.py)):
`run_type = RunType.LIST_OF_TASKS`. Parses `payload["tasks"]` into
`list[AgentTaskSpec]` (raises `AgentServiceError` if empty or if task names
are not unique), resolves the agent **once**, then runs each task
sequentially through `run_task_through_loop` with a **fresh** `AgentContext`
per task. `AgentTaskSpec.context` names earlier tasks whose outputs are
injected as an instructions preamble via `format_context_preamble`, delimited
by `"===== PREVIOUS TASKS OUTPUTS ====="` / `"===== END PREVIOUS TASKS OUTPUTS ====="`;
referencing a task that has not yet produced output (unknown name, or a task
later in the sequence) raises `AgentServiceError`. If any task's
`result.stop_reason` is in `FAILURE_STOP_REASONS`, the runner raises
`AgentServiceError` for the whole request. Per-task outcomes accumulate into
`TaskRunSummary` objects, and `emitter.on_task_start` / `on_task_finish` are
called around each task.

Shared helper `run_task_through_loop`
([`src/agent/app/runners/task_execution.py`](../../src/agent/app/runners/task_execution.py)):

- `max_iter = agent.max_iter or max_iter_fn()` (defaults to
  `settings.agent_default_max_iter`, injectable for tests).
- If `output_schema` is set, `as_object_schema(output_schema)` validates its
  shape **before any LLM call** (fail-fast on an unrecognizable schema).
- If `output_schema` **and no tools** are registered: skip the plain loop
  entirely and go straight to `StructuredOutputEnforcer.enforce`, returning a
  `LoopResult` with `stop_reason = StopReason.SCHEMA_SATISFIED.value`.
- Otherwise: run the plain loop (`MaxIterAndNoToolCalls(max_iter)` stop
  policy via `deps.loop.run`) first. If `output_schema` was requested and the
  plain loop's `stop_reason` is in `FAILURE_STOP_REASONS`, raise
  `AgentServiceError` without ever invoking the enforcer. If the plain loop
  succeeded and `output_schema` was requested, run the enforcer and fold its
  usage into the plain loop's `TokenUsage`; the merged `stop_reason` becomes
  `SCHEMA_SATISFIED` unless the plain loop already stopped with
  `MAX_CONSECUTIVE_FAILURES` (that reason is preserved).

## 5. Agent Loop

`DefaultAgentLoop` ([`src/agent/app/loop/agent_loop.py`](../../src/agent/app/loop/agent_loop.py))
is the **only** component that talks to `LLMClient` directly; it is
deliberately ignorant of `RunType`.

`run()` wraps `_run_inner` in `asyncio.wait_for(timeout=context.agent.max_execution_time)`
(skipped entirely when `max_execution_time is None`). A `_RunState` dataclass
(`iterations`, `tool_invocations`, `final_text`, `usage`, `context_warned`,
`consecutive_failures`) is created **outside** `_run_inner` so a timeout or
unexpected exception still returns a partial `LoopResult` built from whatever
progress was made (`stop_reason=TIMEOUT` or `LLM_ERROR` respectively).

`_run_inner` is the ReAct loop body:

1. **Context-window warning**: if `context_warning_ratio > 0`, `litellm.get_model_info`
   resolves the model's context window once per run; each iteration,
   `litellm.token_counter` estimates the current input tokens and
   `emitter.on_warning(...)` fires **once** (`state.context_warned` latches)
   when usage reaches `ratio` (default `0.8`) of the window. Both litellm
   calls are wrapped to return `None` on any exception rather than raising.
2. One streamed LLM call:
   `self._llm.chat(messages=context.messages, tools=tools.tool_specs(), model_config=_build_model_config(context), stream=True, runtime_config={"max_retry_limit": ..., "max_rpm": ...})`.
3. Chunks are accumulated: `delta_text` into a text buffer, tool-call
   fragments keyed by `id` into `tool_buf` (name + concatenated argument
   deltas), usage dicts folded into `state.usage`. An assistant message is
   only appended if there was text or tool calls.
4. Tool dispatch, in order, enforcing two caps per iteration:
   - `max_tool_calls` — calls beyond the cap are **not executed** and get a
     synthetic `ToolResult(is_error=True, ...)` explaining the limit.
   - `max_consecutive_failures` — once the running `consecutive_failures`
     counter reaches the limit, `failure_limit_hit` latches and all
     **remaining** calls in the same iteration are also short-circuited with
     an error `ToolResult` (not executed).
5. `StopPolicy.should_stop(iterations, chunks, complete_calls)` decides
   whether to loop again.

`_execute_tool` coalesces **every** failure mode into
`ToolResult(is_error=True, ...)` — invalid JSON arguments, unknown tool name
(`KeyError` from `ToolRegistry.execute`), per-call timeout
(`asyncio.wait_for(..., timeout=context.agent.tool_timeout)` →
`asyncio.TimeoutError`), and any other exception raised by the executor. Tool
errors **never** abort the loop; they are fed back to the LLM as a `"tool"`
role message.

`_finalize_after_failures` runs once `max_consecutive_failures` consecutive
tool failures are hit: it injects a user message instructing the model to
stop calling tools and summarize, makes **one** final streamed LLM call with
`tools=[]` (and `tool_choice` stripped from `model_config`), and returns a
`LoopResult` with `stop_reason = StopReason.MAX_CONSECUTIVE_FAILURES.value` —
this is a **graceful** stop, not a failure.

`StopPolicy` ABC and `MaxIterAndNoToolCalls`
([`src/agent/app/loop/stop_policy.py`](../../src/agent/app/loop/stop_policy.py)):
stop when `iteration_index >= max_iter` (`MAX_ITER_REACHED`) or the last
iteration produced no tool calls (`COMPLETED`); otherwise continue.

## 6. LLM Layer (`src/agent/app/llm/`)

`client.py` ([`src/agent/app/llm/client.py`](../../src/agent/app/llm/client.py)):
`LLMClient` ABC with a single abstract `chat(...)` returning
`AsyncIterator[LLMChunk]`. `LLMChunk{delta_text, tool_call_fragment,
finish_reason, usage}` — normalized output unit; `ToolCallFragment{id, name,
arguments_delta}` — one streaming fragment of a tool call.

`litellm_client.py` ([`src/agent/app/llm/litellm_client.py`](../../src/agent/app/llm/litellm_client.py)):
`LiteLLMClient` is **streaming-only** — `chat()` asserts `stream is True`.
Converts `ToolSpec`s into the litellm/OpenAI function-call format, resolves a
`Router` from the process-wide `RouterPool`, resolves a `RetryPolicy`
(default `AGENT_DEFAULT_MAX_RETRIES`, overridable per-call via
`runtime_config["max_retry_limit"]`), strips Router-owned/runtime keys before
forwarding to `router.acompletion`
(`_STRIPPED_MODEL_CONFIG_KEYS = {"model", "api_key", "base_url", "api_version", "max_retry_limit", "max_rpm"}`),
calls `router.acompletion(stream=True, stream_options={"include_usage": True}, ...)`
wrapped in `retry.aretry(...)`. Usage/cost normalization happens per chunk:
`_usage_dict` normalizes prompt/completion/total tokens plus
`cached_prompt_tokens` (OpenAI `prompt_tokens_details.cached_tokens`,
Anthropic `cache_read_input_tokens` fallback); `_usage_cost_usd` calls
`litellm.cost_per_token` best-effort, swallowing any exception to `0.0`.

`router_pool.py` ([`src/agent/app/llm/router_pool.py`](../../src/agent/app/llm/router_pool.py)):
`RouterPool` is a process-singleton (`get_router_pool()`) keyed by a
SHA-256 hash of `(model, api_key, base_url, api_version, rpm)`, using
double-checked locking (`asyncio.Lock`) so a Router is built at most once per
config. Each Router holds a **single** deployment (`model_name = key[:12]`)
with `disable_cooldowns=True` — deliberately avoiding the ~60s
"no-deployments-available" outage that cooldowns would otherwise cause on a
single-deployment router. `rpm` is set on the deployment's `litellm_params`
when provided.

`retry.py` ([`src/agent/app/llm/retry.py`](../../src/agent/app/llm/retry.py)):
`RetryPolicy` — exponential backoff with jitter
(`base_delay * 2**attempt + jitter`, capped at `max_delay`). Retryable
exception names: `RateLimitError`, `APIConnectionError`, `Timeout`,
`InternalServerError`, `ServiceUnavailableError`; non-retryable:
`AuthenticationError`, `BadRequestError`, `ContextWindowExceededError`,
`ContentPolicyViolationError`, `NotFoundError` (both lists resolved from the
installed `litellm` version at import time, falling back to
`litellm.APIError` with a warning if a name is missing). `aretry` iterates
`range(max_retries + 1)`.

`config.py` ([`src/agent/app/llm/config.py`](../../src/agent/app/llm/config.py)):
`configure_litellm(drop_unsupported_params)` sets `litellm.drop_params` so
provider-unsupported params (e.g. `presence_penalty` on Anthropic) are
silently dropped instead of raising.

## 7. Structured Output (`src/agent/app/output/`)

`enforcer.py` ([`src/agent/app/output/enforcer.py`](../../src/agent/app/output/enforcer.py)):
`StructuredOutputEnforcer.enforce` loops `range(max_retries + 1)`. Each
attempt:

1. Registers a **fresh** `submit_final_answer` tool (`build_answer_tool`) in a
   new `ToolRegistry`.
2. Forces `context.tool_choice = {"type": "function", "function": {"name": "submit_final_answer"}}`.
3. Appends a corrective user message (starts as a generic instruction to call
   the tool; escalates wording on repeated failures).
4. Runs the loop for exactly one turn:
   `self._loop.run(context, registry, emitter, MaxIterAndNoToolCalls(max_iter=1))`.
5. A `stop_reason` in `FAILURE_STOP_REASONS` raises `AgentServiceError`
   immediately (clearing `tool_choice` first).
6. If the tool was never called (`capture.args is None`), the corrective
   message escalates and the loop retries.
7. Otherwise the captured args (unwrapped from `{"result": ...}` if the
   schema was non-object and had to be wrapped) are validated via
   `validate_output`. Success returns `(candidate, usage)`; failure feeds the
   validation error back into the next corrective message.
8. Exhausting all attempts raises `SchemaValidationError`.

`schema.py` ([`src/agent/app/output/schema.py`](../../src/agent/app/output/schema.py)):
`as_object_schema(schema)` — tool input schemas must be `type: object`; a
non-dict schema or one missing a top-level `"type"` key raises
`InvalidOutputSchemaError`. Non-object schemas are wrapped as
`{"type": "object", "properties": {"result": schema}, "required": ["result"]}`.
`validate_output` runs `jsonschema.validate`, returning a `ValidationOutcome`;
a `jsonschema.exceptions.SchemaError` (the schema itself is malformed) also
raises `InvalidOutputSchemaError`. `add_usage` sums two `TokenUsage` objects
field-by-field.

System tool: `tools/system_tools/structured_output.py`
([`src/agent/app/tools/system_tools/structured_output.py`](../../src/agent/app/tools/system_tools/structured_output.py)) —
`build_answer_tool(output_schema)` builds the `submit_final_answer` `ToolSpec`
plus an `AnswerCapture` executor that just records `args` and returns a
placeholder `ToolResult`; this is the only file under `system_tools/` today.

## 8. Tools & Resources

`tools/registry.py` ([`src/agent/app/tools/registry.py`](../../src/agent/app/tools/registry.py)):
`ToolRegistry` maps `name → (ToolSpec, async executor)`. `tool_specs()` feeds
`LLMClient.chat`; `execute(name, args)` dispatches by name, raising `KeyError`
for an unregistered name (caught by `DefaultAgentLoop._execute_tool`).

`tools/registry_builder.py` ([`src/agent/app/tools/registry_builder.py`](../../src/agent/app/tools/registry_builder.py)):
`ToolRegistryBuilder` — fluent, single-use (`RuntimeError` on reuse). All
names are sanitized to `^[A-Za-z0-9_-]{1,64}$` via `sanitize_tool_name`; a
collision after sanitisation raises `DuplicateToolNameError`.
`add_system_tools()`, `add_python_code_tool(data)`, `add_mcp_tool(data, *, name, description, args_schema)`,
`add_knowledge_tools(collection)`. Knowledge tools: one `_naive`-suffixed
tool per naive `SearchConfigEntry`, and one `_graph`-suffixed tool per unique
graph `rag_id` (entries with the same `rag_id` merge into a single tool
exposing a `search_method` enum parameter — `basic`/`local`). Name
collisions are disambiguated by appending `_{rag_id}`.

`resources/resolver.py` ([`src/agent/app/resources/resolver.py`](../../src/agent/app/resources/resolver.py)):
`AgentResolver.resolve(agent, request)` indexes the three request pools by
key, then for each `tool_ref` dispatches by the `unique_name` prefix (split
on `":"`):
- `python-code-tool` → `builder.add_python_code_tool(entry.data)`.
- `mcp-tool` → `mcp_gateway.describe(entry.data)` then
  `builder.add_mcp_tool(...)`.
- any other prefix (e.g. `configured-tool`, `proxy-tool`) → raises
  `AgentServiceError` — those tool types are **crew-only**, not supported in
  the agent service.

Missing refs raise `UnknownToolRefError` / `UnknownCollectionRefError` /
`UnknownS3RefError`. `collection_refs` → `builder.add_knowledge_tools(...)`.
`s3_refs` are validated for presence only — `AgentResolver` does **not**
fetch S3 content this pass, it only carries the path forward. Returns a
`ResolvedAgent{agent_id, context: AgentContext, tools: ToolRegistry, attachments}`.

Executors (`tools/executors/`), all returning `ToolResult`:
- `python_code.py` `PythonCodeToolExecutor` → `SandboxClient.submit(CodeTaskData(...))`.
- `mcp_tool.py` `McpToolExecutor` → `McpToolGateway.call`, mapping `McpToolError` to an error `ToolResult`.
- `knowledge_search.py` `KnowledgeSearchExecutor` (single target) and
  `GraphKnowledgeSearchExecutor` (method-dispatched: `basic`/`local`, falling
  back to the default method for an unknown/missing `search_method`) → both
  call `KnowledgeClient.search`, with `NAIVE_RAG_SEARCH_TIMEOUT = 20.0`s and
  `GRAPH_RAG_SEARCH_TIMEOUT = 120.0`s (env-overridable).

Out-of-process transport clients (`sandbox/client.py`, `knowledge/client.py`,
`tools/mcp/gateway.py`):
- `SandboxClient` ([`src/agent/app/sandbox/client.py`](../../src/agent/app/sandbox/client.py)) —
  Redis pub/sub on `code_exec_tasks` (request) / `code_results` (response),
  correlated by `execution_id`; a background reader task resolves pending
  `asyncio.Future`s.
- `KnowledgeClient` ([`src/agent/app/knowledge/client.py`](../../src/agent/app/knowledge/client.py)) —
  Redis pub/sub on `knowledge:search:get` (request) / `knowledge:search:response`
  (response), correlated by a generated `uuid`.
- `McpToolGateway` ([`src/agent/app/tools/mcp/gateway.py`](../../src/agent/app/tools/mcp/gateway.py)) —
  in-process FastMCP client (`FastMCPClientFactory`); `describe()` calls
  `list_tools()`, `call()` calls `call_tool()`. Both wrap client-level
  exceptions into `McpToolError`.

## 9. Result Streaming (`src/agent/app/emitters/`)

`Emitter` ABC ([`src/agent/app/emitters/base.py`](../../src/agent/app/emitters/base.py)) —
a Bridge between the execution layers (`Runner`, `AgentLoop`) and the output
transport. Hooks: `on_start`, `on_chunk`, `on_tool_call`, `on_tool_result`,
`on_warning`, `on_final`, `on_error` (all abstract), plus optional
`on_task_start` / `on_task_finish` (default no-ops, overridden only by
`RedisStreamToolEventEmitter`). All publish to the `agent.results` stream.

`redis_batch.py` ([`src/agent/app/emitters/redis_batch.py`](../../src/agent/app/emitters/redis_batch.py)):
`RedisStreamBatchEmitter` buffers every event internally and publishes
**exactly one** envelope on `on_final` (`type="agent.result"`, payload:
`final_text`, `tool_invocations`, `iterations`, `stop_reason`, `token_usage`,
`error`, `events` (buffered), `warnings`, `tasks`) or `on_error`
(`type="agent.error"`, payload: `error`, `warnings`).

`redis_tool_events.py` ([`src/agent/app/emitters/redis_tool_events.py`](../../src/agent/app/emitters/redis_tool_events.py)):
`RedisStreamToolEventEmitter` extends the batch emitter (used by **both**
`SingleTaskRunner` and `ListOfTasksRunner`). It publishes live, best-effort
envelopes in addition to the terminal batch payload: `agent.tool_call` /
`agent.tool_result` (content/arguments truncated at `LIVE_CONTENT_MAX_CHARS`
/ `LIVE_ARGUMENTS_MAX_CHARS` = 2000 chars each, with a per-event token-usage
delta via `TokenUsageAccumulator.consume_delta()`), plus `agent.task_start` /
`agent.task_finish` for `ListOfTasksRunner` runs. A live-publish failure is
logged and swallowed — it never aborts the run.

`EmitterMode` enum (`app/enums.py`): `BATCH`, `TOOL_EVENTS` (both
implemented), `STREAM` (reserved for a future `ChatRunner` /
`RedisStreamDeltaEmitter`; `RunnerFactory._build_emitter` raises
`NotImplementedError` for it today).

## 10. Directory Structure

```
src/agent/
├── main.py                          # entry point, consumer loop, DI wiring
├── settings.py                      # Settings dataclass + load_settings()
└── app/
    ├── constants.py                 # re-exports FAILURE_STOP_REASONS, StopReason
    ├── data_loader.py                # DataLoader
    ├── enums.py                     # EmitterMode; re-exports RunType
    ├── exceptions.py                # AgentServiceError hierarchy
    ├── factory.py                   # RunnerFactory
    ├── request_handler.py           # RequestHandler
    ├── usage.py                     # TokenUsageAccumulator
    ├── logging_utils.py             # redact()/redacted_dump()
    ├── llm/
    │   ├── client.py                 # LLMClient ABC, LLMChunk, ToolCallFragment
    │   ├── litellm_client.py         # LiteLLMClient
    │   ├── router_pool.py            # RouterPool (process singleton)
    │   ├── retry.py                  # RetryPolicy
    │   └── config.py                 # configure_litellm()
    ├── loop/
    │   ├── agent_loop.py              # AgentLoop ABC, DefaultAgentLoop
    │   ├── context.py                 # AgentContext
    │   └── stop_policy.py             # StopPolicy ABC, MaxIterAndNoToolCalls
    ├── runners/
    │   ├── base.py                    # Runner ABC
    │   ├── deps.py                    # RunnerDependencies
    │   ├── single_task.py             # SingleTaskRunner
    │   ├── list_of_tasks.py           # ListOfTasksRunner
    │   └── task_execution.py          # run_task_through_loop()
    ├── output/
    │   ├── enforcer.py                # StructuredOutputEnforcer
    │   └── schema.py                  # as_object_schema, validate_output, add_usage
    ├── emitters/
    │   ├── base.py                    # Emitter ABC
    │   ├── redis_batch.py             # RedisStreamBatchEmitter
    │   └── redis_tool_events.py       # RedisStreamToolEventEmitter
    ├── prompt/
    │   ├── base.py                     # PromptBuilder ABC
    │   └── single_task.py              # SingleTaskPromptBuilder
    ├── resources/
    │   └── resolver.py                 # AgentResolver, ResolvedAgent
    ├── tools/
    │   ├── registry.py                  # ToolRegistry, ToolSpec
    │   ├── registry_builder.py          # ToolRegistryBuilder
    │   ├── system_registry.py           # SystemToolRegistry, @system_tool decorator
    │   ├── executors/
    │   │   ├── python_code.py            # PythonCodeToolExecutor
    │   │   ├── mcp_tool.py                # McpToolExecutor
    │   │   └── knowledge_search.py        # KnowledgeSearchExecutor, GraphKnowledgeSearchExecutor
    │   ├── mcp/
    │   │   ├── client_factory.py          # FastMCPClientFactory
    │   │   └── gateway.py                 # McpToolGateway
    │   └── system_tools/
    │       └── structured_output.py       # submit_final_answer tool, AnswerCapture
    ├── sandbox/
    │   └── client.py                     # SandboxClient (Redis pub/sub)
    └── knowledge/
        ├── client.py                     # KnowledgeClient (Redis pub/sub)
        └── target.py                     # KnowledgeSearchTarget
```

## 11. End-to-End Sequence Diagram

```mermaid
sequenceDiagram
    participant Stream as Redis Stream (agent.requests)
    participant Main as main() consume loop
    participant Handler as RequestHandler
    participant Loader as DataLoader
    participant Factory as RunnerFactory
    participant Runner as Runner (SingleTask/ListOfTasks)
    participant Prompt as PromptBuilder
    participant Exec as run_task_through_loop
    participant Loop as DefaultAgentLoop
    participant LLM as LiteLLMClient (RouterPool/RetryPolicy)
    participant Tools as ToolRegistry
    participant Backend as Sandbox / MCP / Knowledge
    participant Enforcer as StructuredOutputEnforcer
    participant Emitter as Emitter (RedisStreamToolEventEmitter)
    participant Results as Redis Stream (agent.results)

    Stream->>Main: XREADGROUP (agent.requests)
    Main->>Main: parse StreamEnvelope (poison pill ack+drop on failure)
    Main->>Handler: handle(envelope, message_id, stream)
    Handler->>Loader: load(envelope)
    Loader->>Loader: GET request_key from Redis K/V
    Loader-->>Handler: AgentRequest
    Handler->>Factory: build(request, redis_client, result_stream)
    Factory-->>Handler: (Runner, Emitter)
    Handler->>Runner: execute(request, emitter)
    Runner->>Emitter: on_start(request)
    Runner->>Prompt: build(agent, instructions, output_schema, attachments)
    Prompt-->>Runner: initial messages
    Runner->>Exec: run_task_through_loop(deps, agent, context, tools, output_schema, emitter)
    Exec->>Loop: run(context, tools, emitter, MaxIterAndNoToolCalls)
    loop until StopPolicy says stop
        Loop->>LLM: chat(messages, tools, model_config, stream=True)
        LLM-->>Loop: LLMChunk stream (text / tool_call_fragment / usage)
        Loop->>Emitter: on_chunk(chunk)
        Loop->>Tools: execute(name, args)
        Tools->>Backend: dispatch (sandbox / MCP / knowledge search)
        Backend-->>Tools: ToolResult
        Loop->>Emitter: on_tool_call / on_tool_result (live events)
    end
    Loop-->>Exec: LoopResult
    opt output_schema requested
        Exec->>Enforcer: enforce(context, output_schema, emitter)
        Enforcer->>Loop: run(context, single-turn registry, emitter, max_iter=1)
        Loop-->>Enforcer: LoopResult (submit_final_answer call)
        Enforcer-->>Exec: (validated candidate, usage)
    end
    Exec-->>Runner: final LoopResult
    Runner->>Emitter: on_final(result)
    Emitter->>Results: publish agent.result envelope
    Handler->>Stream: XACK message_id
```
