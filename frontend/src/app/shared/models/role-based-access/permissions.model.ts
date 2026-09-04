export enum ActionCode {
    Create = 'create',
    Read = 'read',
    Update = 'update',
    Delete = 'delete',
    Export = 'export',
    Use = 'use', // for 'secrets' management only
    List = 'list', // unused for now
}

export enum ResourceCode {
    Organizations = 'organizations',
    Memberships = 'memberships',
    Roles = 'roles',
    Flows = 'flows',
    Agents = 'agents',
    Tools = 'tools',
    KnowledgeSources = 'knowledge_sources',
    Files = 'files',
    LlmConfigs = 'llm_configs',
    Secrets = 'secrets',
}

export interface ActivePermissions {
    org_id: number;
    is_superadmin: boolean;
    role: { id: number; name: string } | null;
    permissions: '*' | Record<ResourceCode, ActionCode[]>;
}

export interface CatalogAction {
    code: ActionCode;
    label: string;
    bit: number;
}

export interface RecommendedPermission {
    resource_type: ResourceCode;
    action: ActionCode;
}

export interface CatalogResourceType {
    code: ResourceCode;
    label: string;
    group: string;
    description: string;
    applicable_actions: ActionCode[];
    /** Global, superadmin-only actions that are never grantable via a role.
     *  For `organizations`: `['create','delete']`; empty (`[]`) for everything else. */
    platform_actions: ActionCode[];
    recommended_with: Record<ActionCode, RecommendedPermission[]>;
}

export interface CatalogResponse {
    actions: CatalogAction[];
    resource_types: CatalogResourceType[];
}

export interface OrgCapability {
    org: { id: number; name: string };
    role: { id: number; name: string };
    permissions: Record<ResourceCode, ActionCode[]>;
}

/** Response from `GET /api/permissions/me/orgs/`.
 *  - Superadmin: `{ is_superadmin: true, permissions: '*' }` (no `orgs`).
 *  - Regular user: `{ is_superadmin: false, orgs: [...] }` (no `permissions`). */
export interface MyOrgPermissionsResponse {
    is_superadmin: boolean;
    orgs?: OrgCapability[];
    permissions?: '*';
}
