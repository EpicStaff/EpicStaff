from datetime import UTC, datetime

from domain.usage import IndexingRunUsage, merge_indexing_usage
from infrastructure.usage_cost import llm_cost, sum_costs


def _run(
    embedding_tokens: int = 10,
    llm_input_tokens: int | None = None,
    llm_output_tokens: int | None = None,
    cost_usd: float | None = 0.5,
) -> IndexingRunUsage:
    return IndexingRunUsage(
        embedding_tokens=embedding_tokens,
        llm_input_tokens=llm_input_tokens,
        llm_output_tokens=llm_output_tokens,
        cost_usd=cost_usd,
        completed_at=datetime(2026, 10, 13, 8, 0, tzinfo=UTC),
    )


def test_first_run_becomes_last_run_and_total():
    merged = merge_indexing_usage({}, _run(llm_input_tokens=100, llm_output_tokens=20))

    assert merged["last_run"] == {
        "embedding_tokens": 10,
        "llm_input_tokens": 100,
        "llm_output_tokens": 20,
        "cost_usd": 0.5,
        "completed_at": "2026-10-13T08:00:00Z",
    }
    assert merged["total"] == {
        "embedding_tokens": 10,
        "llm_input_tokens": 100,
        "llm_output_tokens": 20,
        "cost_usd": 0.5,
    }


def test_later_run_replaces_last_run_and_adds_to_total():
    first = merge_indexing_usage({}, _run(10, 100, 20, 0.5))

    merged = merge_indexing_usage(first, _run(5, 50, 10, 0.25))

    assert merged["last_run"]["embedding_tokens"] == 5
    assert merged["total"] == {
        "embedding_tokens": 15,
        "llm_input_tokens": 150,
        "llm_output_tokens": 30,
        "cost_usd": 0.75,
    }


def test_naive_run_keeps_llm_fields_null():
    merged = merge_indexing_usage(merge_indexing_usage({}, _run()), _run())

    assert merged["total"]["llm_input_tokens"] is None
    assert merged["total"]["llm_output_tokens"] is None
    assert merged["total"]["embedding_tokens"] == 20


def test_unpriced_run_makes_total_cost_null_and_it_stays_null():
    after_unpriced = merge_indexing_usage(merge_indexing_usage({}, _run()), _run(cost_usd=None))
    assert after_unpriced["total"]["cost_usd"] is None

    after_priced = merge_indexing_usage(after_unpriced, _run(cost_usd=0.5))
    assert after_priced["total"]["cost_usd"] is None
    assert after_priced["last_run"]["cost_usd"] == 0.5


def test_llm_cost_prefers_custom_prices_when_both_are_set():
    assert llm_cost("openai/gpt-4o-mini", 10, 5, 1.0, 2.0) == 20.0


def test_llm_cost_uses_price_map_when_only_one_custom_price_is_set():
    mapped = llm_cost("openai/gpt-4o-mini", 10, 5)
    assert mapped is not None
    assert llm_cost("openai/gpt-4o-mini", 10, 5, 1.0, None) == mapped


def test_llm_cost_is_null_for_an_unpriced_model():
    assert llm_cost("openai/no-such-llm", 10, 5) is None


def test_sum_costs_is_null_when_any_cost_is_unknown():
    assert sum_costs(1.0, 2.0) == 3.0
    assert sum_costs(1.0, None) is None
