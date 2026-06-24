export type ActionCode = 'create' | 'read' | 'update' | 'delete' | 'export' | 'download' | 'use' | 'list';

export type ResourceCode =
    | 'organizations'
    | 'users'
    | 'roles'
    | 'flows'
    | 'agents'
    | 'tools'
    | 'knowledge_sources'
    | 'files'
    | 'projects'
    | 'llm_configs'
    | 'secrets';

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

export interface CatalogResourceType {
    code: string;
    label: string;
    group: string;
    description: string;
    applicable_actions: ActionCode[];
}

export interface CatalogResponse {
    actions: CatalogAction[];
    resource_types: CatalogResourceType[];
}
