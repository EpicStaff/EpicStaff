// transcription.model.ts

export interface GetTranscriptionConfigRequest {
    id: number;
    custom_name: string;
    api_key: string;
    realtime_transcription_model: number;
}

export interface CreateTranscriptionConfigRequest {
    custom_name: string;
    api_key: string;
    realtime_transcription_model: number;
}

export interface UpdateTranscriptionConfigRequest {
    id: number;
    custom_name?: string;
    api_key?: string;
    realtime_transcription_model?: number;
}

export interface EnhancedTranscriptionConfig extends GetTranscriptionConfigRequest {
    model_name: string;
}

export interface GetRealtimeTranscriptionModelRequest {
    id: number;
    name: string;
    provider: number;
    is_custom: boolean;
}

export interface CreateRealtimeTranscriptionModelRequest {
    name: string;
    provider: number;
    is_custom: boolean;
}
