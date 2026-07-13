export enum ActionCode {
    Create = 'create',
    Read = 'read',
    Update = 'update',
    Delete = 'delete',
    Export = 'export',
    Download = 'download',
    Use = 'use',
    List = 'list',
}

export enum ResourceCode {
    Organizations = 'organizations',
    Users = 'users',
    Roles = 'roles',
    Flows = 'flows',
    Agents = 'agents',
    Tools = 'tools',
    KnowledgeSources = 'knowledge_sources',
    Files = 'files',
    Projects = 'projects',
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
