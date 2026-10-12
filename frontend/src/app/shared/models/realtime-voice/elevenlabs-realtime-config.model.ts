import { AuthorshipFields } from '../authorship.model';

export interface ElevenLabsRealtimeConfig extends AuthorshipFields {
    id: number;
    custom_name: string;
    api_key_secret_id: number | null;
    model_name: string;
    language: string | null;
    /** Read-only ISO 8601 creation time; null for configs created before it was recorded. Never sent back. */
    created_at: string | null;
}

export interface CreateElevenLabsRealtimeConfigRequest {
    custom_name: string;
    api_key_secret_id?: number | null;
    model_name?: string;
    language?: string | null;
}

export interface UpdateElevenLabsRealtimeConfigRequest extends CreateElevenLabsRealtimeConfigRequest {
    id: number;
}
