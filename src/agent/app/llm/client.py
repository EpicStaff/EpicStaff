"""
Layer 2 — LLMClient ABC and normalized chunk models.

Wraps the LiteLLM provider API behind a single async streaming interface.
``AgentLoop`` depends only on this ABC; the concrete implementation (LiteLLM
call, provider auth, retry logic) is a follow-up plan.

Non-streaming requests must also return an ``AsyncIterator[LLMChunk]``
containing exactly one item so the loop has a single codepath regardless of
``stream`` mode.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from pydantic import BaseModel, ConfigDict


class ToolCallFragment(BaseModel):
    """One streaming fragment of a tool-call produced by the LLM.

    Multiple fragments with the same ``id`` are accumulated by ``AgentLoop``
    into a complete tool call before dispatch.
    """

    model_config = ConfigDict(frozen=True)

    id: str  # opaque tool-call id assigned by the LLM provider (e.g. "call_abc123")
    name: str
    arguments_delta: str


class LLMChunk(BaseModel):
    """Normalized unit of output from ``LLMClient.chat``.

    Exactly one field will be populated per chunk depending on what the
    provider returned: incremental text (``delta_text``), a tool-call
    fragment (``tool_call_fragment``), the finish signal
    (``finish_reason``), or token usage stats (``usage``).
    """

    model_config = ConfigDict(frozen=True)

    delta_text: str | None = None
    tool_call_fragment: ToolCallFragment | None = None
    finish_reason: str | None = None
    usage: dict | None = None


class LLMClient(ABC):
    """Abstract LiteLLM facade consumed by ``AgentLoop``.

    Implementations must normalize provider-specific streaming formats into
    the ``LLMChunk`` schema so the loop has no provider awareness.

    Body to be implemented in follow-up plan — see plan §'What is NOT in this plan'.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list,
        model_config: dict,
        *,
        stream: bool,
        runtime_config: dict | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Return an async iterator of normalized ``LLMChunk`` objects.

        When ``stream=False`` the iterator must yield exactly one chunk
        containing the complete response so callers have a single codepath.

        Args:
            messages: conversation history in OpenAI chat format.
            tools: list of tool specs in provider-compatible format (from
                ``ToolRegistry.tool_specs()``).
            model_config: arbitrary keyword args forwarded to LiteLLM
                (model name, temperature, max_tokens, etc.) from
                ``AgentConfig.params``.
            stream: whether to request token-by-token streaming from the
                provider.
            runtime_config: optional dict carrying ``max_retry_limit`` and
                ``max_rpm`` sourced from ``AgentConfig``; kept separate from
                ``model_config`` so ``model_config`` stays LiteLLM-kwargs only.
        """
        ...
