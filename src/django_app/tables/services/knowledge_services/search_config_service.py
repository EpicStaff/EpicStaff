"""Suggests good search settings for a RAG collection.

IN:  facts about the collection (how many documents, how many chunks, the
     average chunk size) and the LLM context window size.
DO:  small math formulas turn those numbers into search settings. Bigger
     collections get bigger settings. Token settings are kept under a safe
     part of the context window. The user can also send their own values;
     those always win.
OUT: one ready settings object per search method (naive, or graph basic /
     local / global / drift), plus the list of fields we had to lower to
     fit the budget. It can also say which graph method fits best.
"""

import math
from dataclasses import dataclass
from typing import Callable, get_args

from pydantic import BaseModel

from src.shared.models.search_config_suggestion import (
    SuggestedCollectionMetrics,
    GraphSearchMethod,
)
from src.shared.models.knowledge import (
    GraphRagBasicSearchParams,
    GraphRagDriftSearchParams,
    GraphRagGlobalSearchParams,
    GraphRagLocalSearchParams,
    NaiveRagSearchConfig,
)
from tables.constants.knowledge_constants import MAX_TOKEN_FIELD_VALUE


SAFE_FRACTION = 0.8


def _lerp_buckets(
    value: float,
    anchors: list[tuple[float, float]],
    *,
    round_to_int: bool = False,
    round_decimals: int = 3,
    log_x: bool = False,
) -> float | int:
    """Linear interpolation between sorted (x, y) anchors, clamped to the end anchors.
    `round_to_int` for integer fields; otherwise rounded to `round_decimals`.
    `log_x` interpolates in log10(x) space (corpus sizes are log-distributed);
    requires anchor x > 0 and treats `value <= 0` as the first anchor.
    """
    if log_x:
        xs = [(math.log10(x), y) for x, y in anchors]
        # value <= 0 is below the first anchor; -inf routes it through the clamp.
        v = math.log10(value) if value > 0 else float("-inf")
    else:
        xs = anchors
        v = value

    if v <= xs[0][0]:
        result = xs[0][1]
    elif v >= xs[-1][0]:
        result = xs[-1][1]
    else:
        # `v` is strictly inside the anchor range, so one segment below
        # always matches and overwrites this. Kept only as a safety net against
        # an UnboundLocalError if anchors were ever malformed (unsorted/empty).
        result = xs[-1][1]
        for (x0, y0), (x1, y1) in zip(xs, xs[1:]):
            if x0 <= v <= x1:
                result = y0 + (y1 - y0) * (v - x0) / (x1 - x0)
                break
    if round_to_int:
        return int(round(result))
    return round(result, round_decimals)


def _lerp_int_log(value: float, anchors: list[tuple[float, float]]) -> int:
    """Integer, log-scaled anchor lookup — the default shape for corpus-driven fields."""
    return _lerp_buckets(value, anchors, round_to_int=True, log_x=True)


def calc_naive_search_limit(total_chunks: int) -> int:
    """How many chunks to retrieve; grows with corpus size."""
    return _lerp_int_log(
        total_chunks,
        [(50, 3), (500, 5), (5000, 8), (50000, 10), (500000, 12), (5000000, 15)],
    )


def calc_naive_similarity_threshold(total_chunks: int) -> float:
    """Min similarity to keep a chunk; raised for bigger corpora (more near-duplicates)."""
    return _lerp_buckets(
        total_chunks,
        [
            (50, 0.15),
            (500, 0.20),
            (5000, 0.25),
            (50000, 0.30),
            (500000, 0.33),
            (5000000, 0.35),
        ],
        log_x=True,
    )


def calc_top_k(total_chunks: int) -> int:
    """Shared formula for `k`, `top_k_entities`, `top_k_relationships`, etc."""
    return _lerp_int_log(
        total_chunks,
        [
            (50, 5),
            (500, 10),
            (5000, 15),
            (50000, 20),
            (500000, 25),
            (5000000, 30),
        ],
    )


def calc_text_unit_prop(avg_chunk_size: float) -> float:
    """Local search text_unit_prop from avg chunk size (bigger chunks → more).
    Capped at 0.65 to leave room for community and local-context slices."""
    return _lerp_buckets(
        avg_chunk_size,
        [(400, 0.40), (1200, 0.65)],
    )


def calc_community_prop(total_documents: int) -> float:
    """Local search community_prop from corpus size (small share for tiny corpora).
    Linear, not log — it's a bounded proportion. Caller must keep
    text_unit_prop + community_prop <= 1.0 so the worker's local slice stays >= 0."""
    return _lerp_buckets(
        total_documents,
        [(5, 0.10), (50, 0.20), (500, 0.25), (5000, 0.30)],
    )


def calc_global_map_max_length(total_chunks: int) -> int:
    """Global map-step answer length; grows with corpus size."""
    return _lerp_int_log(
        total_chunks,
        [(500, 1000), (5000, 1500), (50000, 2000), (500000, 2500)],
    )


def calc_global_reduce_max_length(total_chunks: int) -> int:
    """Global reduce-step answer length; grows with corpus size."""
    return _lerp_int_log(
        total_chunks,
        [(500, 2000), (5000, 3000), (50000, 3500), (500000, 4000)],
    )


def calc_global_dynamic_search_threshold(total_documents: int) -> int:
    """Rating bar for dynamic community selection; stricter for bigger corpora."""
    return _lerp_int_log(
        total_documents,
        [(50, 1), (5000, 2), (500000, 3)],
    )


def calc_community_level(total_documents: int) -> int:
    """Max community-tree depth to include; grows with corpus size, capped at 5.
    Shared by static community_level and global's dynamic_search_max_level."""
    return _lerp_int_log(
        total_documents,
        [(5, 1), (50, 2), (500, 3), (5000, 4), (50000, 5)],
    )


def calc_drift_concurrency(total_chunks: int) -> int:
    """Parallel drift requests; grows with corpus size, capped at 96 to avoid rate limits."""
    return _lerp_int_log(
        total_chunks,
        [(500, 16), (5000, 32), (50000, 64), (500000, 96)],
    )


def calc_drift_k_followups(total_chunks: int) -> int:
    """Drift follow-ups ≈ √N, clamped to 3..25 to bound cost."""
    if total_chunks < 1:
        return 3
    raw = int(math.sqrt(total_chunks) / 3)
    return max(3, min(25, raw))


def calc_conversation_history_max_turns(safe_budget_value: int) -> int:
    """Prior turns in local search context (~1000 tokens/turn), clamped to 2..5."""
    return max(2, min(5, safe_budget_value // 5000))


def calc_drift_primer_folds(total_documents: int) -> int:
    """Drift primer folds; grows with corpus size."""
    return _lerp_int_log(
        total_documents,
        [(5, 3), (50, 5), (500, 7), (5000, 9), (50000, 12)],
    )


def calc_drift_n_depth(total_documents: int) -> int:
    """Drift descent depth; deeper for small corpora, floors at 2 for large."""
    return _lerp_int_log(
        total_documents,
        [(5, 4), (50, 3), (500, 2)],
    )


def safe_budget(target_ctx: int, is_trusted: bool = True) -> int:
    """Token budget = ctx × SAFE_FRACTION. Untrusted ctx (user override or
    fallback, not litellm) is capped at MAX_TOKEN_FIELD_VALUE so a mistyped
    override can't push suggestions to absurd values.
    """
    raw = int(target_ctx * SAFE_FRACTION)
    if is_trusted:
        return raw
    return min(raw, MAX_TOKEN_FIELD_VALUE)


def clamp_token_fields(
    fields: dict[str, int | None],
    budget: int,
    is_trusted: bool,
) -> tuple[dict[str, int | None], list[str]]:
    """Clamp token-typed fields to `budget`, returning (clamped_values, clamped_names).
    Untrusted ctx disables clamping — the user may know their custom model
    supports more; the save-side DRF serializer still enforces the hard cap.
    """
    if not is_trusted:
        return dict(fields), []

    out: dict[str, int | None] = {}
    clamped: list[str] = []
    for name, value in fields.items():
        if value is None:
            out[name] = None
        elif value > budget:
            out[name] = budget
            clamped.append(name)
        else:
            out[name] = value
    return out, clamped


def _pick(custom: dict | None, key: str, default):
    """Return `custom[key]` if supplied, else `default`. An explicit None counts
    as "not supplied" (means "use suggested default").
    """
    if custom is None:
        return default
    if key not in custom or custom[key] is None:
        return default
    return custom[key]


def default_data_tokens(
    metrics: SuggestedCollectionMetrics,
    budget: int,
    ctx_share: float,
    corpus_share: float,
) -> int:
    """Per-method default for a token field: max of ctx_share × budget and
    corpus_share × corpus_tokens, floored at 1000 and capped at budget. The max
    keeps small corpora from starving and large ones from exceeding the LLM ceiling.
    """
    corpus_tokens = int(metrics.total_chunks * max(metrics.avg_chunk_size, 0.0))
    by_ctx = int(budget * ctx_share)
    by_corpus = int(corpus_tokens * corpus_share)
    return min(budget, max(1000, by_ctx, by_corpus))


def _rebalance_props(text_unit: float, community: float) -> tuple[float, float]:
    """Keep text_unit_prop + community_prop <= 1.0 (the worker derives
    local_prop = 1 - text - community and rejects sum > 1). Clamp each to
    [0, 1]; normalize proportionally only if the sum exceeds 1, else leave as-is.
    """
    text_unit = max(0.0, min(1.0, float(text_unit)))
    community = max(0.0, min(1.0, float(community)))
    total = text_unit + community
    if total > 1.0:
        text_unit = round(text_unit / total, 10)
        community = round(community / total, 10)
    return text_unit, community


def _resolved_props(
    custom: dict | None,
    metrics: SuggestedCollectionMetrics,
    text_key: str,
    community_key: str,
) -> tuple[float, float]:
    """Resolve text_unit / community proportions (override → formula) and rebalance
    to sum <= 1.0. Shared by local and drift builders (they differ only in key names).
    """
    text_unit = _pick(custom, text_key, calc_text_unit_prop(metrics.avg_chunk_size))
    community = _pick(
        custom, community_key, calc_community_prop(metrics.total_documents)
    )
    return _rebalance_props(text_unit, community)


def build_naive_params(
    metrics: SuggestedCollectionMetrics,
    custom: dict | None,
) -> tuple[NaiveRagSearchConfig, list[str]]:
    chunks = metrics.total_chunks
    fields = {
        "search_limit": _pick(custom, "search_limit", calc_naive_search_limit(chunks)),
        "similarity_threshold": _pick(
            custom, "similarity_threshold", calc_naive_similarity_threshold(chunks)
        ),
    }
    return NaiveRagSearchConfig(**fields), []


def build_graph_basic_params(
    metrics: SuggestedCollectionMetrics,
    ctx: int,
    is_trusted: bool,
    custom: dict | None,
) -> tuple[GraphRagBasicSearchParams, list[str]]:
    chunks = metrics.total_chunks
    default_budget = safe_budget(ctx, is_trusted)
    token_fields, clamped = clamp_token_fields(
        {
            "max_context_tokens": _pick(custom, "max_context_tokens", default_budget),
        },
        default_budget,
        is_trusted,
    )
    return (
        GraphRagBasicSearchParams(
            prompt=_pick(custom, "prompt", None),
            k=_pick(custom, "k", calc_top_k(chunks)),
            **token_fields,
        ),
        clamped,
    )


def build_graph_local_params(
    metrics: SuggestedCollectionMetrics,
    ctx: int,
    is_trusted: bool,
    custom: dict | None,
) -> tuple[GraphRagLocalSearchParams, list[str]]:
    chunks = metrics.total_chunks
    docs = metrics.total_documents
    top_k = calc_top_k(chunks)

    text_unit, community = _resolved_props(
        custom, metrics, "text_unit_prop", "community_prop"
    )

    default_budget = safe_budget(ctx, is_trusted)
    token_fields, clamped = clamp_token_fields(
        {
            "max_context_tokens": _pick(custom, "max_context_tokens", default_budget),
        },
        default_budget,
        is_trusted,
    )
    return (
        GraphRagLocalSearchParams(
            prompt=_pick(custom, "prompt", None),
            text_unit_prop=text_unit,
            community_prop=community,
            conversation_history_max_turns=_pick(
                custom,
                "conversation_history_max_turns",
                calc_conversation_history_max_turns(default_budget),
            ),
            top_k_entities=_pick(custom, "top_k_entities", top_k),
            top_k_relationships=_pick(custom, "top_k_relationships", top_k),
            community_level=_pick(
                custom, "community_level", calc_community_level(docs)
            ),
            **token_fields,
        ),
        clamped,
    )


def build_graph_global_params(
    metrics: SuggestedCollectionMetrics,
    ctx: int,
    is_trusted: bool,
    custom: dict | None,
) -> tuple[GraphRagGlobalSearchParams, list[str]]:
    chunks = metrics.total_chunks
    docs = metrics.total_documents
    default_budget = safe_budget(ctx, is_trusted)
    token_fields, clamped = clamp_token_fields(
        {
            "max_context_tokens": _pick(custom, "max_context_tokens", default_budget),
            "data_max_tokens": _pick(
                custom,
                "data_max_tokens",
                default_data_tokens(metrics, default_budget, 0.3, 0.3),
            ),
        },
        default_budget,
        is_trusted,
    )
    return (
        GraphRagGlobalSearchParams(
            dynamic_community_selection=_pick(
                custom, "dynamic_community_selection", docs > 50
            ),
            map_prompt=_pick(custom, "map_prompt", None),
            reduce_prompt=_pick(custom, "reduce_prompt", None),
            knowledge_prompt=_pick(custom, "knowledge_prompt", None),
            map_max_length=_pick(
                custom, "map_max_length", calc_global_map_max_length(chunks)
            ),
            reduce_max_length=_pick(
                custom, "reduce_max_length", calc_global_reduce_max_length(chunks)
            ),
            dynamic_search_threshold=_pick(
                custom,
                "dynamic_search_threshold",
                calc_global_dynamic_search_threshold(docs),
            ),
            dynamic_search_keep_parent=_pick(
                custom, "dynamic_search_keep_parent", docs > 100
            ),
            dynamic_search_use_summary=_pick(
                custom, "dynamic_search_use_summary", docs > 100
            ),
            dynamic_search_max_level=_pick(
                custom,
                "dynamic_search_max_level",
                calc_community_level(docs),
            ),
            dynamic_search_num_repeats=_pick(custom, "dynamic_search_num_repeats", 1),
            **token_fields,
        ),
        clamped,
    )


def build_graph_drift_params(
    metrics: SuggestedCollectionMetrics,
    ctx: int,
    is_trusted: bool,
    custom: dict | None,
) -> tuple[GraphRagDriftSearchParams, list[str]]:
    chunks = metrics.total_chunks
    docs = metrics.total_documents
    top_k = calc_top_k(chunks)

    text_unit, community = _resolved_props(
        custom, metrics, "local_search_text_unit_prop", "local_search_community_prop"
    )

    default_budget = safe_budget(ctx, is_trusted)
    token_fields, clamped = clamp_token_fields(
        {
            "data_max_tokens": _pick(custom, "data_max_tokens", default_budget),
            "reduce_max_tokens": _pick(custom, "reduce_max_tokens", None),
            "primer_llm_max_tokens": _pick(
                custom,
                "primer_llm_max_tokens",
                default_data_tokens(metrics, default_budget, 0.5, 0.6),
            ),
            "local_search_max_data_tokens": _pick(
                custom,
                "local_search_max_data_tokens",
                default_data_tokens(metrics, default_budget, 0.25, 0.2),
            ),
            "local_search_llm_max_gen_tokens": _pick(
                custom, "local_search_llm_max_gen_tokens", None
            ),
            "reduce_max_completion_tokens": _pick(
                custom, "reduce_max_completion_tokens", None
            ),
            "local_search_llm_max_gen_completion_tokens": _pick(
                custom, "local_search_llm_max_gen_completion_tokens", None
            ),
        },
        default_budget,
        is_trusted,
    )
    return (
        GraphRagDriftSearchParams(
            prompt=_pick(custom, "prompt", None),
            reduce_prompt=_pick(custom, "reduce_prompt", None),
            concurrency=_pick(custom, "concurrency", calc_drift_concurrency(chunks)),
            drift_k_followups=_pick(
                custom, "drift_k_followups", calc_drift_k_followups(chunks)
            ),
            primer_folds=_pick(custom, "primer_folds", calc_drift_primer_folds(docs)),
            n_depth=_pick(custom, "n_depth", calc_drift_n_depth(docs)),
            community_level=_pick(
                custom, "community_level", calc_community_level(docs)
            ),
            local_search_text_unit_prop=text_unit,
            local_search_community_prop=community,
            local_search_top_k_mapped_entities=_pick(
                custom, "local_search_top_k_mapped_entities", top_k
            ),
            local_search_top_k_relationships=_pick(
                custom, "local_search_top_k_relationships", top_k
            ),
            reduce_temperature=0.0,
            local_search_temperature=0.0,
            local_search_top_p=_pick(custom, "local_search_top_p", 1.0),
            local_search_n=_pick(custom, "local_search_n", 1),
            **token_fields,
        ),
        clamped,
    )


BuilderFn = Callable[
    [SuggestedCollectionMetrics, int, bool, dict | None],
    tuple[BaseModel, list[str]],
]


@dataclass(frozen=True)
class SearchMethodStrategy:
    """Pairing of a graph search method name with its params builder."""

    method_name: str
    builder: BuilderFn
    params_class: type[BaseModel]


"""
GRAPH_SEARCH_METHOD_REGISTRY — single source of truth for Graph RAG
search methods supported by the suggest endpoint.

To add a new search method:
  1. Add a `build_*_params(metrics, ctx, is_trusted, custom)` function
     above that returns `(PydanticModel, clamped_fields)`.
  2. Add one SearchMethodStrategy line here.
Everything else (view dispatch, validation) updates automatically.
"""

GRAPH_SEARCH_METHOD_REGISTRY: list[SearchMethodStrategy] = [
    SearchMethodStrategy("basic", build_graph_basic_params, GraphRagBasicSearchParams),
    SearchMethodStrategy("local", build_graph_local_params, GraphRagLocalSearchParams),
    SearchMethodStrategy(
        "global", build_graph_global_params, GraphRagGlobalSearchParams
    ),
    SearchMethodStrategy("drift", build_graph_drift_params, GraphRagDriftSearchParams),
]

# Fail fast at import time if the registry and the canonical `GraphSearchMethod`
# Literal (the API contract) ever drift apart — e.g., a method added to one but
# not the other.
assert {s.method_name for s in GRAPH_SEARCH_METHOD_REGISTRY} == set(
    get_args(GraphSearchMethod)
), "GRAPH_SEARCH_METHOD_REGISTRY is out of sync with GraphSearchMethod Literal"


def get_graph_strategy(method_name: str) -> SearchMethodStrategy:
    """Return the registry entry for `method_name` or raise ValueError."""
    for strategy in GRAPH_SEARCH_METHOD_REGISTRY:
        if strategy.method_name == method_name:
            return strategy
    raise ValueError(f"Unknown graph search method: {method_name}")


@dataclass(frozen=True)
class MethodApplicability:
    """Predicate-based applicability rule for one graph search method.

    `predicate(metrics)` returns True when this method is the recommended
    default for a corpus with those metrics. Predicates may inspect any
    field of SuggestedCollectionMetrics (total_documents, total_chunks,
    avg_chunk_size, or derived quantities).
    """

    method_name: str
    predicate: Callable[[SuggestedCollectionMetrics], bool]


GRAPH_METHOD_RECOMMENDATION_ORDER: list[MethodApplicability] = [
    MethodApplicability(
        "basic",
        lambda m: m.total_chunks < 50 or m.total_documents < 2,
    ),
    MethodApplicability(
        "local",
        lambda m: m.total_chunks < 1500 and m.total_documents < 10,
    ),
    MethodApplicability(
        "drift",
        lambda m: m.total_chunks < 15000 and m.total_documents < 100,
    ),
    MethodApplicability(
        "global",
        lambda _m: True,  # catch-all — must be last.
    ),
]


def recommend_graph_search_method(metrics: SuggestedCollectionMetrics) -> str:
    """Recommend the optimal graph RAG search method for this corpus size.

    Walks GRAPH_METHOD_RECOMMENDATION_ORDER and returns the first method
    whose predicate is True. The final catch-all guarantees a result.
    """
    for applicability in GRAPH_METHOD_RECOMMENDATION_ORDER:
        if applicability.predicate(metrics):
            return applicability.method_name
    # Unreachable: the last entry is a catch-all. Guard for tampering.
    raise RuntimeError(
        "GRAPH_METHOD_RECOMMENDATION_ORDER must end with a catch-all entry."
    )
