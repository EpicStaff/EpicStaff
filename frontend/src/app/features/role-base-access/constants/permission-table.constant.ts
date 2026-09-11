import { ActionCode } from '@shared/models';

export const ACTION_ICONS: Partial<Record<ActionCode, string>> = {
    create: 'plus',
    read: 'eye',
    update: 'edit',
    delete: 'trash',
    export: 'download',
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
