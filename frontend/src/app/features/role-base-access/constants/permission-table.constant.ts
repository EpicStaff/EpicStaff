import { ActionCode } from '@shared/models';

export const ACTION_ICONS: Partial<Record<ActionCode, string>> = {
    create: 'plus',
    read: 'eye',
    update: 'edit',
    delete: 'trash',
    export: 'download',
    download: 'download',
    use: 'play',
    list: 'list',
};

export interface GroupMeta {
    label: string;
    icon: string;
}

export const GROUP_META: Record<string, GroupMeta> = {
    admin: { label: 'Organizations & Access', icon: 'buildings' },
    workspace: { label: 'Workspace Resources', icon: 'workspace' },
    config: { label: 'Configuration & Secrets', icon: 'settings' },
};

export interface ResourceMeta {
    description: string;
}

export const RESOURCE_META: Record<string, ResourceMeta> = {
    organizations: { description: 'Create, rename, deactivate organizations' },
    users: { description: 'Add/remove members, assign roles within org' },
    roles: { description: 'Create/edit custom roles and assign to users' },
    flows: { description: 'Automation pipelines' },
    agents: { description: 'Manage AI agents and their capabilities' },
    tools: { description: 'Manage built-in and custom tools' },
    knowledge_sources: { description: 'RAG collections and embeddings' },
    files: { description: 'Files and folders in organization storage' },
    projects: { description: 'Organize AI agents and tasks' },
    llm_configs: { description: 'LLM model configurations and settings' },
    secrets: { description: 'Provider API keys, credentials, sensitive config' },
};
