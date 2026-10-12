import { AuthorshipFields } from '../authorship.model';

export interface GeminiRealtimeConfig extends AuthorshipFields {
    id: number;
    custom_name: string;
    api_key_secret_id: number | null;
    model_name: string;
    voice_recognition_prompt: string | null;
    /** Read-only ISO 8601 creation time; null for configs created before it was recorded. Never sent back. */
    created_at: string | null;
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
