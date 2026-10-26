import { PluginAction, PluginOrganizationRef } from './plugin-admin.model';

/** One permission a plugin declares, as the Roles matrix shows it. */
export interface PluginRoleRowAction {
    action: PluginAction;
    label: string;
    description: string;
}

/** A plugin row of the Roles matrix: a plugin that is running and granted to the organization. */
export interface PluginRoleRow {
    plugin_identifier: string;
    name: string;
    icon_url: string;
    /** The manifest's `user_permissions`, in manifest order. */
    actions: PluginRoleRowAction[];
    /** What the caller may grant in this organization; `[]` when the row is not editable. */
    ceiling: PluginAction[];
}

/** `GET /api/admin/plugin-role-permissions/rows/?org_id=`: the rows for a role about to be created. */
export interface PluginRoleRowsResponse {
    organization: PluginOrganizationRef;
    /** Sorted by name. */
    rows: PluginRoleRow[];
}

export interface PluginRoleRef {
    id: number;
    name: string;
    is_built_in: boolean;
    org_id: number | null;
}

export interface PluginRolePermissionsRow extends PluginRoleRow {
    granted: PluginAction[];
}

/** `GET` and `PUT /api/admin/plugin-role-permissions/{role_id}/`: a role's plugin rows and what it holds on them. */
export interface PluginRolePermissionsResponse {
    role: PluginRoleRef;
    /** `null` only for a built-in role read without `org_id`. */
    organization: PluginOrganizationRef | null;
    /** A custom role whose organization the caller may update roles in. */
    editable: boolean;
    rows: PluginRolePermissionsRow[];
}

/** `PUT` body: a full replacement; a plugin of the role's organization not listed loses its actions. */
export interface PluginRolePermissionsUpdate {
    plugins: { plugin_identifier: string; actions: PluginAction[] }[];
}
