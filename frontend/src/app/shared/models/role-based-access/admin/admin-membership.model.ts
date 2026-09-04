import { Organization, Role } from '../membership.model';

export interface AdminMembershipRow {
    id: number;
    user: AdminMembershipUser;
    role: Role;
    org: Organization;
    joined_at: string;
}

export interface AdminMembershipUser {
    id: number;
    email: string;
    display_name: string | null;
    avatar_url: string | null;
    is_superadmin: boolean;
    is_active: boolean;
}

export type MembershipStatus = 'active' | 'inactive';

export interface ListMembershipsParams {
    org_ids?: number[];
    role_id?: number;
    status?: MembershipStatus;
    search?: string;
    ordering?: string;
    page?: number;
    page_size?: number;
}

export interface AssignableUsersResponse {
    id: number;
    email: string;
    display_name: string | null;
    avatar_url: string | null;
    org_ids: number[];
}

export interface CreateMembershipRequest {
    org_id: number;
    role_id: number;
    email?: string;
    user_id?: number;
}

export interface UpdateMembershipRequest {
    role_id: number;
}
