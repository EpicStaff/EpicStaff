export interface CreateApiKeyRequest {
    name: string;
    expires_in_days: number | null;
}

export interface GetMyApiKeyResponse {
    id: number;
    name: string;
    prefix: string;
    created_at: string;
    expires_at: string | null;
    last_used_at: string | null;
    revoked_at: string | null;
    status: ApiKeyStatus;
}

export interface CreateApiKeyResponse extends GetMyApiKeyResponse {
    api_key: string;
}

export type ApiKeyStatus = 'active' | 'expired' | 'revoked';
