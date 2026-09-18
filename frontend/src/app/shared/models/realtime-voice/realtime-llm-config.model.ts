export interface RealtimeModelConfig {
    id: number;
    custom_name: string;
    api_key_secret_id: number | null;
    realtime_model: number;
    provider_name?: string;
}

export interface CreateRealtimeModelConfigRequest {
    api_key_secret_id: number | null;
    realtime_model: number;
    custom_name: string;
}

export interface UpdateRealtimeModelConfigRequest {
    id: number;
    custom_name: string;
    api_key_secret_id?: number | null;
    realtime_model: number;
}
