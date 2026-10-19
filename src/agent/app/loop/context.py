"""
AgentContext: mutable conversation state for one loop run.

``AgentContext`` is created by ``AgentResolver`` before calling
``AgentLoop.run`` and is mutated in-place by the loop as assistant messages
and tool results are appended.  It is not shared across loop invocations.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from shared.models.agent_service import AgentSpec, ContextAttachment

CancellationCheck = Callable[[], Awaitable[bool]]


class AgentContext:
    """Dumb conversation container: holds agent config and the growing messages list.

    ``messages`` starts empty; the prompt is built externally by the runner
    via ``PromptBuilder`` and injected via ``append_message`` before the loop
    starts.  ``correlation_id`` is carried through for logging and emitter
    correlation.  ``is_cancelled`` reports whether crew withdrew the run; the
    loop checks it before every LLM and tool call.
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

    def append_message(self, message: dict) -> None:
        """Append a single message dict (OpenAI chat format) to the conversation history."""
        self.messages.append(message)
