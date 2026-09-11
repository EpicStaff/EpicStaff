import { FullMembership } from '../membership.model';

export interface AdminCreateUserRequest {
    email: string;
    password: string;
    organization_id?: number;
    role_id?: number;
}

export interface AdminCreateUserResponse {
    id: number;
    email: string;
    avatar_url: string;
    display_name: string;
    is_superadmin: boolean;
    is_active: boolean;
    memberships: FullMembership[];
    created_at: string;
    updated_at: string;
}
