export interface AgentSearchConfigs {
    naive?: NaiveRagSearchConfig;
    graph?: GraphRagSearchConfig;
}

export interface NaiveRagSearchConfig {
    search_limit: number | null;
    similarity_threshold: number | null;
}

export interface GraphRagSearchConfig {
    search_method: GraphSearchMethod;
    basic?: GraphBasicSearchConfig;
    local?: GraphLocalSearchConfig;
    global_search?: GraphGlobalSearchConfig;
    drift_search?: GraphDriftSearchConfig;
}

export type GraphSearchMethod = 'basic' | 'local' | 'global_search' | 'drift_search';

export interface GraphBasicSearchConfig {
    prompt: string | null;
    k: number;
    max_context_tokens: number;
}

export interface GraphLocalSearchConfig {
    prompt: string | null;
    text_unit_prop: number;
    community_prop: number;
    conversation_history_max_turns: number;
    max_context_tokens: number;
    top_k_entities: number;
    top_k_relationships: number;
    community_level: number;
}

export interface GraphGlobalSearchConfig {
    map_prompt: string | null;
    reduce_prompt: string | null;
    knowledge_prompt: string | null;
    max_context_tokens: number;
    data_max_tokens: number;
    map_max_length: number;
    reduce_max_length: number;
    dynamic_community_selection: boolean;
    dynamic_search_threshold: number;
    dynamic_search_keep_parent: boolean;
    dynamic_search_num_repeats: number;
    dynamic_search_use_summary: boolean;
    dynamic_search_max_level: number;
}

export interface GraphDriftSearchConfig {
    prompt: string | null;
    reduce_prompt: string | null;
    data_max_tokens: number;
    reduce_max_tokens: number | null;
    reduce_max_completion_tokens: number | null;
    concurrency: number;
    drift_k_followups: number;
    primer_folds: number;
    primer_llm_max_tokens: number;
    n_depth: number;
    local_search_text_unit_prop: number;
    local_search_community_prop: number;
    local_search_top_k_mapped_entities: number;
    local_search_top_k_relationships: number;
    local_search_max_data_tokens: number;
    local_search_top_p: number;
    local_search_n: number;
    local_search_llm_max_gen_tokens: number | null;
    local_search_llm_max_gen_completion_tokens: number | null;
    community_level: number;
}

export interface SuggestCollectionMetrics {
    total_documents: number;
    total_chunks: number;
    avg_chunk_size: number;
}

export interface SuggestResponse {
    metrics: SuggestCollectionMetrics;
    resolved_llm_name: string | null;
    llm_resolution_warning: string | null;
    effective_llm_context_window: number;
    safe_token_budget: number;
    clamped_fields: string[];
    suggested_params: Record<string, unknown>;
    recommended_search_method?: GraphSearchMethod | null;
}

export interface NaiveSuggestRequest {
    knowledge_collection_id: number;
    llm_config_id: number;
    user_custom_params?: Record<string, unknown> | null;
}

export interface GraphSuggestRequest {
    knowledge_collection_id: number;
    llm_config_id: number;
    search_method: GraphSearchMethod;
    user_custom_params?: Record<string, unknown> | null;
}
