export enum TabId {
    GENERAL = 'general',
    RAG = 'rag',
    LLM_PARAMS = 'llm_params',
    EXECUTION = 'execution',
    ADVANCED = 'advanced',
}

export interface Tab {
    id: TabId;
    label: string;
}
