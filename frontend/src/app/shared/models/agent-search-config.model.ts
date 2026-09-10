export interface AgentSearchConfigs {
    naive?: NaiveRagSearchConfig | null;
    graph?: GraphRagSearchConfig | null;
}

export interface NaiveRagSearchConfig {
    search_limit: number | null;
    similarity_threshold: number | null;
}

export interface GraphRagSearchConfig {
    search_method: GraphSearchMethod;
    basic?: GraphBasicSearchConfig | null;
    local?: GraphLocalSearchConfig | null;
}

export type GraphSearchMethod = 'basic' | 'local';

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
}
