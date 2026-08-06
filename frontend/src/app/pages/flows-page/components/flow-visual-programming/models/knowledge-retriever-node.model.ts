import { AgentSearchConfigs } from '@shared/models';

export interface GetKnowledgeRetrieverNodeRequest {
    id: number;
    graph: number | null;
    source_collection: number | null;
    search_configs: AgentSearchConfigs | null;
    created_at: string;
    updated_at: string;
    metadata: Record<string, unknown>;
    node_name: string;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    query: string;
    search_method: 'basic' | 'local' | null;
    rag_type: number | null;
    content_hash: string | null;
}
