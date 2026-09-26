import { truncateName } from '../../utils/surface/surface-collection-conflict.util';
import { PersistenceMode } from '../models/persistence-node.model';

/** The longest table name the canvas caption shows whole; a longer one is cut to end in "…". */
export const CAPTION_TABLE_NAME_LIMIT = 20;

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

/** The subtitle for the caption under the node, its table name cut to CAPTION_TABLE_NAME_LIMIT. */
export function persistenceCaption(mode: PersistenceMode, tableName: string | null, keyCount: number): string {
    const shownName = tableName === null ? null : truncateName(tableName, CAPTION_TABLE_NAME_LIMIT);
    return persistenceSubtitle(mode, shownName, keyCount);
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
