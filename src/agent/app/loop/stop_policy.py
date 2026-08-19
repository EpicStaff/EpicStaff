"""
Layer 3 support — StopPolicy: pluggable termination strategy for ``AgentLoop``.

The stop policy is the single decision point that tells the loop whether to
perform another LLM call or return.  Runners inject an appropriate policy
when constructing the loop invocation, keeping termination logic out of both
the loop body and the runner.  ``StopDecision`` carries both the boolean and
the human-readable stop reason so the loop no longer needs to classify the
reason separately.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.llm.client import LLMChunk
from shared.models.agent_service import StopReason


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: str = ""


class StopPolicy(ABC):
    """Abstract strategy that decides when an ``AgentLoop`` iteration should end.

    ``AgentLoop`` calls ``should_stop`` after each iteration with the current
    index, the chunks received from the LLM, and any tool calls that were
    accumulated.  Subclasses encode domain-specific termination rules and
    return a ``StopDecision`` with both the flag and the reason string.
    """

    @abstractmethod
    def should_stop(
        self,
        iteration_index: int,
        last_chunks: list[LLMChunk],
        last_tool_calls: list,
    ) -> StopDecision:
        """Return a ``StopDecision`` describing whether and why to stop.

        Args:
            iteration_index: zero-based count of completed iterations.
            last_chunks: all ``LLMChunk`` objects received in this iteration.
            last_tool_calls: tool-call objects accumulated from this iteration's
                chunks.  An empty list means the LLM produced a plain text
                response with no tool use.
        """
        ...


class MaxIterAndNoToolCalls(StopPolicy):
    """Default stop policy: stop when the iteration cap is reached or the
    LLM response contains no tool calls.

    Satisfies the common case: keep looping only while the model is using
    tools; once it returns plain text (or the safety cap is hit), stop.
    ``max_iter`` guards against infinite tool-call chains.
    """

    def __init__(self, max_iter: int) -> None:
        self._max_iter = max_iter

    def should_stop(
        self,
        iteration_index: int,
        last_chunks: list[LLMChunk],
        last_tool_calls: list,
    ) -> StopDecision:
        """Return a ``StopDecision`` with reason ``max_iter_reached`` or ``completed``."""
        if iteration_index >= self._max_iter:
            return StopDecision(True, StopReason.MAX_ITER_REACHED.value)

        if not last_tool_calls:
            return StopDecision(True, StopReason.COMPLETED.value)

        return StopDecision(False)
