"""
Contract DTOs for the agent microservice request/response cycle.

These frozen models are the single source of truth shared between the agent
service producer (django_app / DataLoader) and the agent service consumer
(AgentLoop, Emitter, AgentResolver).

Hierarchy
---------
``AgentRequest``        — top-level envelope produced by ``DataLoader``.
    ``AgentSpec``           — per-agent configuration with resource references.
    ``BaseToolData``        — (imported from shared.models.tools) pool entry.
    ``CollectionSpec``      — pool entry for a source collection with one or more RAGs.
        ``SearchConfigEntry``   — one RAG strategy within a collection.
    ``S3FileSpec``          — pool entry for an S3-hosted file.
``RunType``             — execution-mode enum; kept here so no agent→shared dep exists.
``LoopResult``          — summary returned by ``AgentLoop.run``.
``ToolResult``          — outcome of a single tool execution.
``ContextAttachment``   — message injected before the first LLM call.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .ai_providers import EmbedderData, LLMData
from .knowledge import RagSearchConfig
from .tools import BaseToolData


class AgentTaskSpec(BaseModel):
    """Shape of one entry in ``AgentRequest.payload["tasks"]`` for ``run_type=LIST_OF_TASKS``.

    ``context`` carries the names of earlier tasks whose outputs should be
    injected before this task runs.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    instructions: str
    output_schema: dict | None = None
    context: list[str] = []


class RunType(str, Enum):
    """Execution mode for an agent request.

    ``SINGLE_TASK`` — one prompt, one ``AgentLoop`` invocation.
    ``LIST_OF_TASKS`` — sequential list of prompts, each run through the loop.
    ``CHAT`` and ``TEAM`` are reserved for future runner implementations.
    """

    SINGLE_TASK = "SINGLE_TASK"
    LIST_OF_TASKS = "LIST_OF_TASKS"


class StopReason(str, Enum):
    """Terminal reason for one AgentLoop run; travels on LoopResult.stop_reason to crew/FE."""

    COMPLETED = "completed"  # agent returned a final answer, stopped calling tools
    MAX_ITER_REACHED = "max_iter_reached"
    SCHEMA_SATISFIED = "schema_satisfied"
    LLM_ERROR = "llm_error"
    TIMEOUT = "timeout"
    MAX_CONSECUTIVE_FAILURES = "max_consecutive_failures"  # tool loop stopped after N consecutive tool failures; graceful summary produced
    MAX_TOOL_CALLS_REACHED = "max_tool_calls_reached"  # tool-call budget for the run exhausted; graceful summary produced


FAILURE_STOP_REASONS = frozenset({StopReason.LLM_ERROR, StopReason.TIMEOUT})


class SearchConfigEntry(BaseModel):
    """One RAG strategy available within a source collection.

    A collection may expose multiple entries (e.g. naive + graph-basic +
    graph-local).  ``AgentResolver`` builds one search tool per entry so the
    LLM can choose the appropriate strategy at runtime.

    ``embedder`` itself is not part of the ``BaseKnowledgeSearchMessage``
    wire format -- ``ToolRegistryBuilder`` extracts ``embedder.config.api_key``
    onto ``KnowledgeSearchTarget.embedder_api_key``, which is what actually
    reaches the wire message.
    """

    model_config = ConfigDict(frozen=True)

    rag_id: int
    rag_type: Literal["naive", "graph"]
    search_config: RagSearchConfig
    embedder: EmbedderData


class CollectionSpec(BaseModel):
    """Immutable pool entry for a source collection.

    Carried on ``AgentRequest.collections``; referenced by
    ``AgentSpec.collection_refs`` via ``unique_name``.  A collection bundles
    one or more ``SearchConfigEntry`` items — each becomes a distinct tool
    registered by ``ToolRegistryBuilder.add_knowledge_tools``.
    """

    model_config = ConfigDict(frozen=True)

    unique_name: str
    collection_id: int
    name: str
    description: str | None = None
    """Optional LLM-facing context appended to each generated tool description."""
    search_configs: list[SearchConfigEntry] = Field(min_length=1)
    """At least one search strategy must be present."""


class AgentSpec(BaseModel):
    """Immutable per-agent configuration with resource references.

    ``tool_refs``, ``collection_refs``, and ``s3_refs`` are identifiers into
    the top-level resource pools on ``AgentRequest``.  ``AgentResolver``
    resolves them into live executors / attachments before the loop starts.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    instructions: str
    llm: LLMData
    fcm_llm: LLMData | None = None
    max_iter: int | None = None
    schema_max_retries: int | None = None
    """Structured-output enforcer retry attempts (``range(n + 1)`` tries); ``None`` uses the env default."""
    max_rpm: int | None = None
    max_execution_time: float | None = None
    """Wall-clock budget in seconds honored by ``DefaultAgentLoop``; ``None`` means no limit."""
    cache: bool | None = None
    max_retry_limit: int | None = None
    """Maximum LLM call retry attempts; ``None`` uses the client default."""
    default_temperature: float | None = None
    max_tool_calls: int | None = None
    """Maximum tool calls executed per agent run; ``None`` means unlimited."""
    tool_timeout: int | None = None
    """Per-tool-call timeout in seconds; ``None`` means no timeout."""
    max_consecutive_failures: int | None = None
    """Consecutive failed tool calls before graceful stop; ``None`` disables the check."""
    tool_refs: list[str] = Field(default_factory=list)
    """unique_name values referencing entries in ``AgentRequest.tools``."""
    collection_refs: list[str] = Field(default_factory=list)
    """unique_name values referencing entries in ``AgentRequest.collections``."""
    s3_refs: list[int] = Field(default_factory=list)
    """id values referencing entries in ``AgentRequest.s3_files``."""


class S3FileSpec(BaseModel):
    """Immutable pool entry for an S3-hosted file.

    Carried on ``AgentRequest.s3_files``; referenced by ``AgentSpec.s3_refs``
    via ``id``.  ``AgentResolver`` validates presence and renders an
    informational access manifest without fetching file content.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    path: str
    metadata: dict = Field(default_factory=dict)


class AgentRequest(BaseModel):
    """Fully hydrated input produced by ``DataLoader`` from a Redis stream envelope.

    ``correlation_id`` is injected by ``DataLoader`` from the envelope; it is
    NOT present in the wire JSON blob stored at the Redis key.  ``RunnerFactory``
    selects a ``Runner`` based on ``run_type``.  ``AgentResolver`` resolves
    per-agent resource refs against the top-level pools (``tools``,
    ``collections``, ``s3_files``).
    """

    model_config = ConfigDict(frozen=True)

    correlation_id: str
    run_type: RunType
    agents: list[AgentSpec]
    tools: list[BaseToolData] = Field(default_factory=list)
    collections: list[CollectionSpec] = Field(default_factory=list)
    s3_files: list[S3FileSpec] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Outcome of a single tool execution dispatched by ``ToolRegistry``.

    ``is_error=True`` signals the loop to treat the content as an error
    message rather than a valid tool response.
    """

    model_config = ConfigDict(frozen=True)

    tool_call_id: str
    content: str
    is_error: bool = False


class ContextAttachment(BaseModel):
    """A message injected into the conversation before the first LLM call.

    Produced by per-type resolvers (e.g. RAG snippets prepended as a system
    message).  ``source`` identifies which resource generated this attachment,
    for logging and debugging.
    """

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user"]
    content: str
    source: str


class TokenUsage(BaseModel):
    """Aggregated token counts for one AgentLoop run."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0
    """Prompt-cache READ tokens served from the provider's cache.

    LiteLLM folds cache reads INTO ``prompt_tokens``, so this is a subset of
    ``prompt_tokens`` and purely informational — it must NEVER be added into
    ``total_tokens``.
    """

    total_cost_usd: float = 0.0
    """Best-effort USD cost derived from litellm's built-in price map.

    ``0.0`` for unmapped or self-hosted models. Display-only — never a source
    of truth for billing and never folded into ``total_tokens``.
    """


class TaskRunSummary(BaseModel):
    """Per-task outcome captured by ``ListOfTasksRunner`` for ``LIST_OF_TASKS`` runs."""

    model_config = ConfigDict(frozen=True)

    name: str
    order: int
    final_text: str | None = None
    structured_output: Any = None
    """Validated output object when the task declared an ``output_schema``; ``None`` otherwise."""
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    iterations: int = 0
    tool_invocations: int = 0
    stop_reason: str | None = None


class LoopResult(BaseModel):
    """Summary returned by ``AgentLoop.run`` after the tool-use cycle ends.

    Consumed by ``Emitter.on_final`` to build the outbound result envelope
    published to ``agent.results``.
    """

    model_config = ConfigDict(frozen=True)

    final_text: str | None
    tool_invocations: int
    iterations: int
    stop_reason: str
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    error: str | None = None
    """Failure detail when stop_reason indicates a failure (llm_error/timeout); None on success."""
    tasks: list[TaskRunSummary] | None = None
    """Per-task summaries for ``LIST_OF_TASKS`` runs; ``None`` for ``SINGLE_TASK`` runs."""
    structured_output: Any = None
    """Validated output object when the task declared an ``output_schema``; ``None`` otherwise."""
