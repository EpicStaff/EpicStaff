import { RagName, RagTypeLevel } from "../enums/rag";

export type RagValueMap = {
    [RagName.NAIVE_RAG]: 'naive';
    [RagName.GRAPH_RAG]: 'graph';
    [RagName.HYBRID_RAG]: 'hybrid';
}

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
    }
}[RagName];

export type RagStatus = 'new' | 'processing' | 'completed' | 'warning' | 'failed';

export type RagType = RagValueMap[keyof RagValueMap];

export interface StartIndexingDtoRequest {
    rag_id: number;
    rag_type: RagType;
}

export interface StartIndexingDtoResponse {
    detail: string;
    rag_id: number;
    rag_type: string;
    collection_id: number;
}
