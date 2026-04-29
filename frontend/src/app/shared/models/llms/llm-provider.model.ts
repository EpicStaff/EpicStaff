export interface LLMProvider {
    id: number;
    name: string;
    description?: string;
}

export enum ModelTypes {
    EMBEDDING = 'embedding',
    REALTIME = 'realtime',
    LLM = 'llm',
    TRANSCRIPTION = 'transcription',
}
