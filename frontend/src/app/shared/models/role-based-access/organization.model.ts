export interface CreateOrganizationRequest {
    name: string;
    audit_retention_days?: number;
}

export interface GetOrganizationResponse {
    id: number;
    name: string;
    is_active: boolean;
    member_count: number;
    admins: OrgAdmin[];
    created_at: string;
    updated_at: string;
    // left out by the backend when the org has no config row yet
    config?: OrganizationConfig;
}

/** Retention in days; 0 means unlimited. The `*_effective_days` values are what the purge applies. */
export interface OrganizationConfig {
    audit_retention_days: number;
    sessions_effective_days: number;
    conversations_effective_days: number;
    audit_effective_days: number;
}

export interface UpdateOrganizationRequest {
    name?: string;
    audit_retention_days?: number;
}

export interface OrgAdmin {
    id: number;
    avatar_url: string | null;
    display_name: string | null;
    email: string;
}
