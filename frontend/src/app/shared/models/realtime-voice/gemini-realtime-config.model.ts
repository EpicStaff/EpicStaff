export interface GeminiRealtimeConfig {
    id: number;
    custom_name: string;
    api_key_secret_id: number | null;
    model_name: string;
    voice_recognition_prompt: string | null;
}

export interface CreateGeminiRealtimeConfigRequest {
    custom_name: string;
    api_key_secret_id?: number | null;
    model_name?: string;
    voice_recognition_prompt?: string | null;
}

export interface UpdateGeminiRealtimeConfigRequest extends CreateGeminiRealtimeConfigRequest {
    id: number;
}
