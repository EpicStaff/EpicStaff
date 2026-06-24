"""Per-request search-param overlay for GraphRAG.

`GraphRagConfigBuilder` builds the *index-time* config once. This module does the
separate, per-request job: take the search params that arrived in the Redis message
and overlay them onto an already-loaded `GraphRagConfig` in place (prompts included,
via `search_prompt_builder`). One applier per search method, plus a single dispatcher
the strategy calls so it doesn't branch on the method itself.
"""

from graphrag.config.models.graph_rag_config import GraphRagConfig

from src.shared.models import (
    GraphRagBasicSearchParams,
    GraphRagLocalSearchParams,
    GraphRagGlobalSearchParams,
    GraphRagDriftSearchParams,
    GraphSearchParams,
)
from rag.graph_rag.utils import (
    build_basic_search_prompt,
    build_local_search_prompt,
    build_drift_search_prompt,
    build_drift_search_reduce_prompt,
    build_global_search_map_prompt,
    build_global_search_reduce_prompt,
)


def apply_basic_search_params(
    config: GraphRagConfig, params: GraphRagBasicSearchParams
) -> None:
    config.basic_search.prompt = build_basic_search_prompt(params.prompt)
    config.basic_search.k = params.k
    config.basic_search.max_context_tokens = params.max_context_tokens


def apply_local_search_params(
    config: GraphRagConfig, params: GraphRagLocalSearchParams
) -> None:
    config.local_search.prompt = build_local_search_prompt(params.prompt)
    config.local_search.text_unit_prop = params.text_unit_prop
    config.local_search.community_prop = params.community_prop
    config.local_search.conversation_history_max_turns = (
        params.conversation_history_max_turns
    )
    config.local_search.top_k_entities = params.top_k_entities
    config.local_search.top_k_relationships = params.top_k_relationships
    config.local_search.max_context_tokens = params.max_context_tokens


def apply_global_search_params(
    config: GraphRagConfig, params: GraphRagGlobalSearchParams
) -> None:
    config.global_search.map_prompt = build_global_search_map_prompt(params.map_prompt)
    # Global search never uses general knowledge: the reduce prompt stays grounded and
    # `knowledge_prompt` is folded in only as a grounded extra instruction. The vendored
    # `knowledge_prompt` path is left unused (and would be inert anyway — the factory
    # hardcodes allow_general_knowledge=False).
    config.global_search.reduce_prompt = build_global_search_reduce_prompt(
        params.reduce_prompt,
        params.knowledge_prompt,
    )
    config.global_search.knowledge_prompt = None
    config.global_search.max_context_tokens = params.max_context_tokens
    config.global_search.data_max_tokens = params.data_max_tokens
    config.global_search.map_max_length = params.map_max_length
    config.global_search.reduce_max_length = params.reduce_max_length
    config.global_search.dynamic_search_threshold = params.dynamic_search_threshold
    config.global_search.dynamic_search_keep_parent = params.dynamic_search_keep_parent
    config.global_search.dynamic_search_num_repeats = params.dynamic_search_num_repeats
    config.global_search.dynamic_search_use_summary = params.dynamic_search_use_summary
    config.global_search.dynamic_search_max_level = params.dynamic_search_max_level


def apply_drift_search_params(
    config: GraphRagConfig, params: GraphRagDriftSearchParams
) -> None:
    config.drift_search.prompt = build_drift_search_prompt(params.prompt)
    config.drift_search.reduce_prompt = build_drift_search_reduce_prompt(
        params.reduce_prompt
    )
    config.drift_search.data_max_tokens = params.data_max_tokens
    config.drift_search.reduce_max_tokens = params.reduce_max_tokens
    config.drift_search.reduce_max_completion_tokens = (
        params.reduce_max_completion_tokens
    )
    config.drift_search.reduce_temperature = params.reduce_temperature
    config.drift_search.concurrency = params.concurrency
    config.drift_search.drift_k_followups = params.drift_k_followups
    config.drift_search.primer_folds = params.primer_folds
    config.drift_search.primer_llm_max_tokens = params.primer_llm_max_tokens
    config.drift_search.n_depth = params.n_depth
    config.drift_search.local_search_text_unit_prop = params.local_search_text_unit_prop
    config.drift_search.local_search_community_prop = params.local_search_community_prop
    config.drift_search.local_search_top_k_mapped_entities = (
        params.local_search_top_k_mapped_entities
    )
    config.drift_search.local_search_top_k_relationships = (
        params.local_search_top_k_relationships
    )
    config.drift_search.local_search_max_data_tokens = (
        params.local_search_max_data_tokens
    )
    config.drift_search.local_search_temperature = params.local_search_temperature
    config.drift_search.local_search_top_p = params.local_search_top_p
    config.drift_search.local_search_n = params.local_search_n
    config.drift_search.local_search_llm_max_gen_tokens = (
        params.local_search_llm_max_gen_tokens
    )
    config.drift_search.local_search_llm_max_gen_completion_tokens = (
        params.local_search_llm_max_gen_completion_tokens
    )


# search_method -> applier. Unknown methods fall back to basic (the strategy's runner
# dispatch defaults the same way).
_APPLIERS = {
    "basic": apply_basic_search_params,
    "local": apply_local_search_params,
    "global_search": apply_global_search_params,
    "drift_search": apply_drift_search_params,
}


def apply_search_params(config: GraphRagConfig, params: GraphSearchParams) -> None:
    """Overlay the request's search params onto `config` in place, by method."""
    _APPLIERS.get(params.search_method, apply_basic_search_params)(config, params)
