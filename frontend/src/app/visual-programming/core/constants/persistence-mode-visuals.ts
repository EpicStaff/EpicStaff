import { PersistenceMode } from '../models/persistence-node.model';

export interface PersistenceModeVisual {
    label: string;
    icon: string;
    accentVar: string;
}

export const PERSISTENCE_MODE_VISUALS: Record<PersistenceMode, PersistenceModeVisual> = {
    read: { label: 'Read', icon: 'ti ti-database-export', accentVar: '--color-status-info' },
    write: { label: 'Write', icon: 'ti ti-database-import', accentVar: '--success-color' },
    delete: { label: 'Delete', icon: 'ti ti-database-x', accentVar: '--color-status-error' },
};

export function persistenceSubtitle(mode: PersistenceMode, tableName: string | null, keyCount: number): string {
    const keys = `${keyCount} ${keyCount === 1 ? 'key' : 'keys'}`;
    return `${PERSISTENCE_MODE_VISUALS[mode].label} · ${tableName ?? 'no table'} · ${keys}`;
}

/** Render-time header icon for a Persistence node, derived from its current mode.
 *  Ignores any icon saved on the node's metadata. */
export function persistenceNodeIcon(mode: PersistenceMode): string {
    return PERSISTENCE_MODE_VISUALS[mode].icon;
}

/** Render-time accent CSS variable for a Persistence node, derived from its current mode.
 *  Ignores any color saved on the node's metadata. */
export function persistenceAccentVar(mode: PersistenceMode): string {
    return PERSISTENCE_MODE_VISUALS[mode].accentVar;
}
