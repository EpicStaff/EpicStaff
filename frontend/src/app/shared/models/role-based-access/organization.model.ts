export interface CreateOrganizationRequest {
    name: string;
}

export interface GetOrganizationResponse {
    id: number;
    name: string;
    is_active: boolean;
    member_count: number;
    admins: OrgAdmin[];
    created_at: string;
    updated_at: string;
}

export interface UpdateOrganizationRequest {
    name?: string;
}

export interface OrgAdmin {
    id: number;
    avatar_url: string | null;
    display_name: string | null;
    email: string;
}
