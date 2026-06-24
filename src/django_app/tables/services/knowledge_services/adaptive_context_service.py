"""Adaptive context management service — pure functions + strategy registry.

Given a `CollectionMetrics` snapshot and the effective LLM context window,
this module produces suggested search-parameter Pydantic models for both
Naive and Graph RAG.
"""

import math
from dataclasses import dataclass
from typing import Callable, get_args

from pydantic import BaseModel

from src.shared.models.adaptive_context import CollectionMetrics, GraphSearchMethod
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
) -> float | int:
    """Linear interpolation between (x, y) anchor points.

    Replaces the step-bucket pattern `if v <= b1: return v1; if v <= b2: ...`
    with a smooth ramp through the same anchor points. At `value <=
    anchors[0][0]` returns the first anchor's y; at `value >= anchors[-1][0]`
    returns the last anchor's y; otherwise linearly interpolates inside the
    segment containing `value`.

    Anchors MUST be sorted by x ascending. For integer-typed fields pass
    `round_to_int=True`; otherwise the result is rounded to `round_decimals`
    decimal places (default 3) to keep responses tidy.
    """
    if value <= anchors[0][0]:
        result = anchors[0][1]
    elif value >= anchors[-1][0]:
        result = anchors[-1][1]
    else:
        # `value` is strictly inside the anchor range, so one segment below
        # always matches and overwrites this. Kept only as a safety net against
        # an UnboundLocalError if anchors were ever malformed (unsorted/empty).
        result = anchors[-1][1]
        for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
            if x0 <= value <= x1:
                result = y0 + (y1 - y0) * (value - x0) / (x1 - x0)
                break
    if round_to_int:
        return int(round(result))
    return round(result, round_decimals)


def calc_naive_search_limit(total_chunks: int) -> int:
    return _lerp_buckets(
        total_chunks,
        [(50, 3), (500, 5), (5000, 8), (50000, 10)],
        round_to_int=True,
    )


def calc_naive_similarity_threshold(total_chunks: int) -> float:
    return _lerp_buckets(
        total_chunks,
        [(50, 0.15), (500, 0.20), (5000, 0.25), (50000, 0.30)],
    )


def calc_top_k(total_chunks: int) -> int:
    """Shared formula for `k`, `top_k_entities`, `top_k_relationships`, etc."""
    return _lerp_buckets(
        total_chunks,
        [(50, 5), (500, 10), (5000, 15), (50000, 20)],
        round_to_int=True,
    )


def calc_text_unit_prop(avg_chunk_size: float) -> float:
    """Local search text_unit_prop driven by average chunk size.

    Bigger chunks carry more raw signal per token, so we lean more on text
    units when chunks are large. Capped at 0.65 so there is always room for
    community summaries (calc_community_prop) AND for the implicit local
    context slice (entity/relationship/covariate = 1 - text - community).
    """
    return _lerp_buckets(
        avg_chunk_size,
        [(400, 0.40), (1200, 0.65)],
    )


def calc_community_prop(total_documents: int) -> float:
    """Local search community_prop driven by collection size.

    Community summaries compress information across many documents — they
    matter more when the corpus is large enough that entity-level signal
    alone is fragmented. For tiny corpora (1-5 docs) communities are nearly
    degenerate, so we give them a small slice. Caller must guarantee that
    `text_unit_prop + community_prop <= 1.0` so the worker's implicit
    `local_prop = 1 - text - community` slice stays non-negative.
    """
    return _lerp_buckets(
        total_documents,
        [(5, 0.10), (50, 0.20), (500, 0.25), (5000, 0.30)],
    )


def calc_global_map_max_length(total_chunks: int) -> int:
    return 1000 if total_chunks <= 500 else 1500


def calc_global_reduce_max_length(total_chunks: int) -> int:
    return 2000 if total_chunks <= 500 else 3000


def calc_global_dynamic_search_threshold(total_documents: int) -> int:
    return 1 if total_documents <= 50 else 2


def calc_community_level(total_documents: int) -> int:
    """Max Leiden community-tree depth to include, driven by corpus size.

    Shared by global search's `dynamic_search_max_level` and the static
    `community_level` used by local / global / drift search — both express
    "how deep into the community hierarchy to go", which scales with corpus
    size the same way.

    Tiny corpora (≤5 docs) have a flat or near-flat community structure
    — depth 1 is enough. Depth grows with corpus size to capture nested
    sub-communities; capped at 4 (the practical maximum that GraphRag's
    Leiden clustering tends to produce).
    """
    return _lerp_buckets(
        total_documents,
        [(5, 1), (50, 2), (500, 3), (5000, 4)],
        round_to_int=True,
    )


def calc_drift_concurrency(total_chunks: int) -> int:
    return _lerp_buckets(
        total_chunks,
        [(500, 16), (5000, 32), (50000, 64)],
        round_to_int=True,
    )


def calc_drift_k_followups(total_chunks: int) -> int:
    """Drift follow-ups grow with √N: small corpora need few extra LLM calls
    (everything fits in the primer), large corpora need more exploration."""
    if total_chunks < 1:
        return 3
    raw = int(math.sqrt(total_chunks) / 3)
    return max(3, min(20, raw))


def calc_conversation_history_max_turns(safe_budget_value: int) -> int:
    """How many prior conversation turns to include in local search context.

    Assumes ~1000 tokens per turn (typical user query + assistant reply with
    citation snippets). Capped at 5 (Pydantic default, also the GraphRag-side
    upper bound for sensible recall) and floored at 2 so degenerate ctx
    (custom small models) still allows at least minimal dialog memory.
    """
    return max(2, min(5, safe_budget_value // 5000))


def calc_drift_primer_folds(total_documents: int) -> int:
    return _lerp_buckets(
        total_documents,
        [(5, 3), (50, 5), (500, 7)],
        round_to_int=True,
    )


def calc_drift_n_depth(total_documents: int) -> int:
    """Drift descent depth: smaller corpora need deeper exploration.

    Anchors are decreasing in y — a small corpus benefits from drilling
    deeper into each followup branch (more recursive expansion) since the
    space is small enough; a large corpus needs broader, shallower coverage.
    """
    return _lerp_buckets(
        total_documents,
        [(5, 4), (50, 3), (500, 2)],
        round_to_int=True,
    )


def safe_budget(target_ctx: int, is_trusted: bool = True) -> int:
    """Token budget for a given LLM context window.

    `is_trusted=True`  → ctx came from litellm (authoritative); use the full
                         `ctx × SAFE_FRACTION` with no artificial ceiling.
    `is_trusted=False` → ctx came from LLMConfig.context_window override or
                         from FALLBACK_CONTEXT_WINDOW; cap at
                         MAX_TOKEN_FIELD_VALUE so a mistyped override (e.g.,
                         "2_000_000" instead of "200_000") cannot push our
                         suggestions to absurd values.
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
    """Clamp token-typed fields to a precomputed `budget` (typically `safe_budget(ctx, is_trusted)`).

    Caller passes the already-resolved budget so builders can reuse the
    same value as both the default and the ceiling without recomputing.

    `is_trusted=False` (litellm did not recognise the model and we are using
    a user override or the global fallback) disables clamping: applying
    safe_budget to user overrides under a guessed ctx is unfair — the user
    may know their custom model supports more. The save-side DRF serializer
    still enforces MAX_TOKEN_FIELD_VALUE as the last line of defence.
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
    """Return `custom[key]` if user supplied it, otherwise `default`.

    Treats an explicit `None` from the user as "not supplied" so that
    formulas / Pydantic defaults are used — matches the spec's intent
    that None in user_custom_params means "use suggested default".
    """
    if custom is None:
        return default
    if key not in custom or custom[key] is None:
        return default
    return custom[key]


def default_data_tokens(
    metrics: CollectionMetrics,
    budget: int,
    ctx_share: float,
    corpus_share: float,
) -> int:
    """Per-method default for a token-typed field.

    Combines two heuristics and takes the larger value, capped at `budget`:
      - `ctx_share`: fraction of safe_budget — LLM-ceiling-driven default.
      - `corpus_share`: fraction of total corpus tokens — data-driven default.

    `max(by_ctx, by_corpus)` ensures small corpora aren't starved by a tiny
    corpus_share, while large corpora can't blow past the LLM ceiling. Both
    fields default to a 1000-token floor so empty/tiny collections still
    produce a meaningful suggestion.

    Caller picks the per-method shares (see build_graph_*_params); this
    helper has no opinion on which method is which.
    """
    corpus_tokens = int(metrics.total_chunks * max(metrics.avg_chunk_size, 0.0))
    by_ctx = int(budget * ctx_share)
    by_corpus = int(corpus_tokens * corpus_share)
    return min(budget, max(1000, by_ctx, by_corpus))


def _rebalance_props(text_unit: float, community: float) -> tuple[float, float]:
    """Ensure text_unit_prop + community_prop <= 1.0, preserving the ratio
    when normalization is needed.

    The worker (graphrag.mixed_context.build_context) derives a third slice
    `local_prop = 1 - text_unit - community` for entity/relationship/covariate
    context, and raises ValueError when the sum > 1. So our job here is NOT
    to force sum == 1 (that would starve the local slice) but to keep the
    sum strictly safe for the worker.

    Strategy:
      1. Clamp each field into [0.0, 1.0].
      2. If the sum exceeds 1.0, normalize proportionally so it becomes 1.0
         (local_prop will be 0 in that case — caller intentionally maxed out).
      3. If the sum is <= 1.0, leave both values as-is; the worker fills the
         remaining budget with local context.
    """
    text_unit = max(0.0, min(1.0, float(text_unit)))
    community = max(0.0, min(1.0, float(community)))
    total = text_unit + community
    if total > 1.0:
        text_unit = round(text_unit / total, 10)
        community = round(community / total, 10)
    return text_unit, community


def build_naive_params(
    metrics: CollectionMetrics,
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
    metrics: CollectionMetrics,
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
    metrics: CollectionMetrics,
    ctx: int,
    is_trusted: bool,
    custom: dict | None,
) -> tuple[GraphRagLocalSearchParams, list[str]]:
    chunks = metrics.total_chunks
    docs = metrics.total_documents
    avg_size = metrics.avg_chunk_size

    text_unit = _pick(custom, "text_unit_prop", calc_text_unit_prop(avg_size))
    community = _pick(custom, "community_prop", calc_community_prop(docs))
    text_unit, community = _rebalance_props(text_unit, community)

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
            top_k_entities=_pick(custom, "top_k_entities", calc_top_k(chunks)),
            top_k_relationships=_pick(
                custom, "top_k_relationships", calc_top_k(chunks)
            ),
            community_level=_pick(
                custom, "community_level", calc_community_level(docs)
            ),
            **token_fields,
        ),
        clamped,
    )


def build_graph_global_params(
    metrics: CollectionMetrics,
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
    metrics: CollectionMetrics,
    ctx: int,
    is_trusted: bool,
    custom: dict | None,
) -> tuple[GraphRagDriftSearchParams, list[str]]:
    chunks = metrics.total_chunks
    docs = metrics.total_documents
    avg_size = metrics.avg_chunk_size

    text_unit = _pick(
        custom, "local_search_text_unit_prop", calc_text_unit_prop(avg_size)
    )
    community = _pick(custom, "local_search_community_prop", calc_community_prop(docs))
    text_unit, community = _rebalance_props(text_unit, community)

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
                custom, "local_search_top_k_mapped_entities", calc_top_k(chunks)
            ),
            local_search_top_k_relationships=_pick(
                custom, "local_search_top_k_relationships", calc_top_k(chunks)
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
    [CollectionMetrics, int, bool, dict | None],
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
        "global_search", build_graph_global_params, GraphRagGlobalSearchParams
    ),
    SearchMethodStrategy(
        "drift_search", build_graph_drift_params, GraphRagDriftSearchParams
    ),
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
    field of CollectionMetrics (total_documents, total_chunks,
    avg_chunk_size, or derived quantities).
    """

    method_name: str
    predicate: Callable[[CollectionMetrics], bool]


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
        "drift_search",
        lambda m: m.total_chunks < 15000 and m.total_documents < 100,
    ),
    MethodApplicability(
        "global_search",
        lambda _m: True,  # catch-all — must be last.
    ),
]


def recommend_graph_search_method(metrics: CollectionMetrics) -> str:
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
