import { RagName, RagTypeLevel } from '../enums/rag';

export type RagValueMap = {
    [RagName.NAIVE_RAG]: 'naive';
    [RagName.GRAPH_RAG]: 'graph';
    [RagName.HYBRID_RAG]: 'hybrid';
};

export interface BaseRagType<T extends RagType> {
    rag_type_id: number;
    rag_type: T;
    source_collection: number;
}

export type Rag = {
    [K in RagName]: {
        name: K;
        value: RagValueMap[K];
        description: string;
        tip: string;
        icon: string;
        level: RagTypeLevel;
        stars: number;
        disabled?: boolean;
    };
}[RagName];

export type RagStatus = 'new' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'partial' | 'outdated';

export type RagType = RagValueMap[keyof RagValueMap];

export interface RagStatusConfiguration {
    rag_id: number;
    rag_type: RagType;
    status: RagStatus;
}

export interface StartIndexingDtoRequest {
    rag_id: number;
    rag_type: RagType;
    document_config_ids?: number[];
}

export interface IndexingEstimate {
    rag_type: RagType;
    document_count: number;
    chunk_count: number;
    embedding: {
        tokens: number;
        exact: boolean;
        cost_usd: number | null;
    };
    llm: {
        calls: number;
        tokens_min: number;
        tokens_max: number;
        cost_usd_min: number | null;
        cost_usd_max: number | null;
    } | null;
}

export interface StopIndexingDtoRequest {
    rag_id: number;
    rag_type: RagType;
}

export interface StartIndexingDtoResponse {
    detail: string;
    rag_id: number;
    rag_type: string;
    collection_id: number;
    accepted_config_ids: number[] | null;
    skipped_completed_config_ids: number[];
}
