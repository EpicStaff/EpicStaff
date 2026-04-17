export interface AgentSearchConfigs {
    naive?: NaiveRagSearchConfig;
    graph?: GraphRagSearchConfig
}

export interface NaiveRagSearchConfig {
    search_limit: number | null;
    similarity_threshold: number | null;
}

export interface GraphRagSearchConfig {
    search_method: GraphSearchMethod;
    basic: GraphBasicSearchConfig;
    local: GraphLocalSearchConfig;
}

export type GraphSearchMethod = 'basic' | 'local';

export interface GraphBasicSearchConfig {
    prompt: string;
    k: number;
    max_context_tokens: number;
}

export interface GraphLocalSearchConfig {
    prompt: string;
    text_unit_prop: number;
    community_prop: number;
    conversation_history_max_turns: number;
    max_context_tokens: number;
    top_k_entities: number;
    top_k_relationships: number;
}
