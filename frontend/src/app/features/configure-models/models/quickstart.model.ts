import {
    EmbeddingConfig,
    GetLlmConfigRequest,
    GetTranscriptionConfigRequest,
    RealtimeModelConfig,
} from '@shared/models';

export interface GetQuickstartResponse {
    supported_providers: string[];
    last_config: QuickstartConfig | null;
    is_synced: boolean;
}

export interface QuickstartConfig {
    config_name: string;
    llm_config: GetLlmConfigRequest;
    embedding_config: EmbeddingConfig;
    realtime_config: RealtimeModelConfig;
    realtime_transcription_config: GetTranscriptionConfigRequest;
}

export interface CreateQuickstartRequest {
    provider: string;
    api_key: string;
}

export interface CreateQuickstartResponse {
    config_name: string;
    configs: QuickstartConfig;
    detail: string;
}
