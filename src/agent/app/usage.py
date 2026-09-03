"""
TokenUsageAccumulator: Information Expert for token/cost accumulation
arithmetic.

Both ``_RunState`` (agent_loop.py) and ``RedisStreamToolEventEmitter``
(redis_tool_events.py) need to accumulate per-chunk usage dicts into running
totals and, in the emitter's case, compute the delta since the last live
event. This dataclass owns that arithmetic once instead of each caller
copy-pasting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.models.agent_service import TokenUsage


@dataclass
class TokenUsageAccumulator:
    """Mutable running total of token usage, with live-delta support.

    ``add`` folds a raw usage dict (as normalized by
    ``app.llm.litellm_client._usage_dict``) into the running totals.
    ``consume_delta`` returns what changed since the last call and advances
    the internal snapshot unconditionally, so callers never double-count
    even if they discard the delta (e.g. a failed publish).
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0
    total_cost_usd: float = 0.0
    _consumed: TokenUsage = field(default_factory=TokenUsage, init=False, repr=False)

    def add(self, usage: dict) -> None:
        """Fold a raw usage dict into the running totals."""
        self.prompt_tokens += int(usage.get("prompt_tokens", 0))
        self.completion_tokens += int(usage.get("completion_tokens", 0))
        self.total_tokens += int(
            usage.get(
                "total_tokens",
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
            )
        )
        self.cached_prompt_tokens += int(usage.get("cached_prompt_tokens", 0))
        self.total_cost_usd += float(usage.get("total_cost_usd", 0.0))

    def to_token_usage(self) -> TokenUsage:
        """Snapshot the running totals as an immutable ``TokenUsage``."""
        return TokenUsage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            cached_prompt_tokens=self.cached_prompt_tokens,
            total_cost_usd=self.total_cost_usd,
        )

    def consume_delta(self) -> dict:
        """Return the usage accumulated since the last ``consume_delta`` call.

        Advances the internal snapshot unconditionally — even if the caller
        never uses (or fails to publish) the returned delta — so the next
        call never double-counts already-reported usage.
        """
        current = self.to_token_usage()
        delta = {
            "prompt_tokens": current.prompt_tokens - self._consumed.prompt_tokens,
            "completion_tokens": current.completion_tokens
            - self._consumed.completion_tokens,
            "total_tokens": current.total_tokens - self._consumed.total_tokens,
            "cached_prompt_tokens": current.cached_prompt_tokens
            - self._consumed.cached_prompt_tokens,
            "total_cost_usd": current.total_cost_usd - self._consumed.total_cost_usd,
        }
        self._consumed = current
        return delta
