import { AuthorshipFields } from '../authorship.model';

export interface OpenAIRealtimeConfig extends AuthorshipFields {
    id: number;
    custom_name: string;
    api_key_secret_id: number | null;
    model_name: string;
    base_url: string | null;
    transcription_model_name: string | null;
    transcription_api_key_secret_id: number | null;
    voice_recognition_prompt: string | null;
    /** Read-only ISO 8601 creation time; null for configs created before it was recorded. Never sent back. */
    created_at: string | null;
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
