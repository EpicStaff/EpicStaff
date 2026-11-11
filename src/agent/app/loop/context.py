"""
AgentContext: mutable conversation state for one loop run.

``AgentContext`` is created by ``AgentResolver`` before calling
``AgentLoop.run`` and is mutated in-place by the loop as assistant messages
and tool results are appended.  It is not shared across loop invocations.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from shared.models.agent_service import AgentSpec, ContextAttachment
from shared.models.ai_providers import LLMData

CancellationCheck = Callable[[], Awaitable[bool]]


class AgentContext:
    """Dumb conversation container: holds agent config and the growing messages list.

    ``messages`` starts empty; the prompt is built externally by the runner
    via ``PromptBuilder`` and injected via ``append_message`` before the loop
    starts.  ``correlation_id`` is carried through for logging and emitter
    correlation.  ``is_cancelled`` reports whether crew withdrew the run; the
    loop checks it before every LLM and tool call.  ``active_llm`` is the LLM
    the loop calls: ``agent.llm`` until ``switch_to_fallback``, then
    ``agent.fallback_llm`` for the rest of this context.
    """

    def __init__(
        self,
        agent: AgentSpec,
        attachments: list[ContextAttachment],
        correlation_id: str,
        messages: list[dict] | None = None,
        tool_choice: dict | None = None,
        *,
        is_cancelled: CancellationCheck,
    ) -> None:
        self.agent = agent
        self.attachments = attachments
        self.correlation_id = correlation_id
        self.messages: list[dict] = messages if messages is not None else []
        self.tool_choice = tool_choice
        self.is_cancelled = is_cancelled
        self.active_llm: LLMData = agent.llm
        self.on_fallback = False

    def append_message(self, message: dict) -> None:
        """Append a single message dict (OpenAI chat format) to the conversation history."""
        self.messages.append(message)

    def switch_to_fallback(self) -> None:
        """Make ``agent.fallback_llm`` the active LLM; the caller checks one is set."""
        self.active_llm = self.agent.fallback_llm
        self.on_fallback = True
