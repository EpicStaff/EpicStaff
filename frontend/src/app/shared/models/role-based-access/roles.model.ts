import { ActionCode } from './permissions.model';

export interface RolePermission {
    resource_type: string;
    actions: ActionCode[];
}

export interface GetRoleResponse {
    id: number;
    name: string;
    description: string | null;
    is_built_in: boolean;
    scope: 'global' | 'org';
    org_id: number | null;
    org: { id: number; name: string } | null;
    assigned_count: number;
    permissions: RolePermission[];
}

/** Envelope returned by `GET /api/admin/roles/`.
 *  Built-ins are returned once (never paginated); custom roles live in `results`. */
export interface RolesListResponse {
    built_in_roles: GetRoleResponse[];
    results: GetRoleResponse[];
    count: number;
    next: string | null;
    previous: string | null;
}

export interface CreateRoleRequest {
    org_id: number;
    name: string;
    description?: string | null;
    permissions: RolePermission[];
}

export interface UpdateRoleRequest {
    name?: string;
    description?: string | null;
    permissions?: RolePermission[];
}

export interface AffectedUser {
    user_id: number;
    email: string;
    display_name: string;
}

/** Response for `DELETE /api/admin/roles/{id}/?dry_run=true`. */
export interface DeleteRolePreviewResponse {
    role_id: number;
    assigned_count: number;
    affected_users: AffectedUser[];
}

/** Response for `DELETE /api/admin/roles/{id}/`. */
export interface DeleteRoleResponse {
    reassigned_count: number;
}
