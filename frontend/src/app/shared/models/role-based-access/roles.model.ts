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
    scope: string;
    org_id: number | null;
    assigned_count: number;
    permissions: RolePermission[];
}

export interface CreateRoleRequest {
    name: string;
    description: string | null;
    permissions: RolePermission[];
}

export interface UpdateRoleRequest {
    name: string;
    description: string | null;
    permissions: RolePermission[];
}
