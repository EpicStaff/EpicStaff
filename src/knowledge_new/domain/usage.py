from dataclasses import dataclass
from datetime import datetime

from src.shared.models.base import ValueObject


@dataclass
class UsageTally:
    """Running token counts of one index run, filled in as provider calls return."""

    embedding_tokens: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.embedding_tokens or self.llm_input_tokens or self.llm_output_tokens)


class IndexingRunUsage(ValueObject):
    """What one index run consumed, as stored under `last_run` of a RAG's `indexing_usage`.

    The `llm_*` fields are None for a RAG that makes no LLM calls (naive). `cost_usd`
    is None when any consumed component has no known price.
    """

    embedding_tokens: int
    llm_input_tokens: int | None
    llm_output_tokens: int | None
    cost_usd: float | None
    completed_at: datetime


def merge_indexing_usage(stored: dict | None, run: IndexingRunUsage) -> dict:
    """Return `stored` (a RAG's `indexing_usage`) with `run` as `last_run` and added to `total`.

    `total.cost_usd` is None once any run's cost was unknown: a sum over only the
    priced runs would understate what the RAG cost.
    """
    previous_total = (stored or {}).get("total") or {}
    previous_cost = previous_total.get("cost_usd", 0.0) if previous_total else 0.0
    has_llm = run.llm_input_tokens is not None
    return {
        "last_run": run.model_dump(mode="json"),
        "total": {
            "embedding_tokens": previous_total.get("embedding_tokens", 0) + run.embedding_tokens,
            "llm_input_tokens": (
                previous_total.get("llm_input_tokens", 0) + run.llm_input_tokens
                if has_llm
                else None
            ),
            "llm_output_tokens": (
                previous_total.get("llm_output_tokens", 0) + run.llm_output_tokens
                if has_llm
                else None
            ),
            "cost_usd": (
                None
                if run.cost_usd is None or previous_cost is None
                else previous_cost + run.cost_usd
            ),
        },
    }
