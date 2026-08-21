import { Organization, Role } from '../membership.model';

/** Row from GET /api/admin/memberships/ — one row per user-in-org. */
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

/** POST /api/admin/memberships/ — link an existing account to an org. Send exactly one of email | user_id. */
export interface CreateMembershipRequest {
    org_id: number;
    role_id: number;
    email?: string;
    user_id?: number;
}

export interface UpdateMembershipRequest {
    role_id: number;
}
