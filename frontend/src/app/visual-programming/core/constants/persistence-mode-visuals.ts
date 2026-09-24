import { PersistenceMode } from '../models/persistence-node.model';

export interface PersistenceModeVisual {
    label: string;
    icon: string;
    accentVar: string;
}

export const PERSISTENCE_MODE_VISUALS: Record<PersistenceMode, PersistenceModeVisual> = {
    read: { label: 'Read', icon: 'ti ti-download', accentVar: '--color-status-info' },
    write: { label: 'Write', icon: 'ti ti-upload', accentVar: '--success-color' },
    delete: { label: 'Delete', icon: 'ti ti-trash', accentVar: '--color-status-error' },
};

export function persistenceSubtitle(mode: PersistenceMode, tableName: string | null, keyCount: number): string {
    const keys = `${keyCount} ${keyCount === 1 ? 'key' : 'keys'}`;
    return `${PERSISTENCE_MODE_VISUALS[mode].label} · ${tableName ?? 'no table'} · ${keys}`;
}
