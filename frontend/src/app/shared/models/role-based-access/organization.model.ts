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
    config?: { audit_retention_days: number };
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
