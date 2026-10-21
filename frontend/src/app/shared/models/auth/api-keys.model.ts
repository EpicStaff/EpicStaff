export enum ApiKeyStatus {
    ACTIVE = 'active',
    EXPIRED = 'expired',
    REVOKED = 'revoked',
}

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

export interface ApiKeyOwner {
    id: number;
    email: string;
    display_name: string;
    avatar_url: string | null;
}

export interface GetApiKeyWithOwnerResponse extends GetMyApiKeyResponse {
    /** `null` when the caller may not read memberships in any of the key's organizations. */
    owner: ApiKeyOwner | null;
    org_ids: number[];
}
