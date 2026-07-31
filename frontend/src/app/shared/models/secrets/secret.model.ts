export interface Secret {
    id: number;
    name: string;
    tail: string;
    metadata: Record<string, unknown> | null;
    org: number;
    created_by: number | null;
    created_at: string;
    updated_at: string;
}

export interface CreateSecretRequest {
    name: string;
    value: string;
    metadata?: Record<string, unknown>;
}
