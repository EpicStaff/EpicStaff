export interface OpenAIRealtimeConfig {
    id: number;
    custom_name: string;
    api_key_secret_id: number | null;
    model_name: string;
    base_url: string | null;
    transcription_model_name: string | null;
    transcription_api_key_secret_id: number | null;
    voice_recognition_prompt: string | null;
}

export interface CreateOpenAIRealtimeConfigRequest {
    custom_name: string;
    api_key_secret_id?: number | null;
    model_name?: string;
    base_url?: string | null;
    transcription_model_name?: string | null;
    transcription_api_key_secret_id?: number | null;
    voice_recognition_prompt?: string | null;
}

export interface UpdateOpenAIRealtimeConfigRequest extends CreateOpenAIRealtimeConfigRequest {
    id: number;
}
