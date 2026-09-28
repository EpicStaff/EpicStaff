import { truncateName } from '../../utils/surface/surface-collection-conflict.util';
import { PersistenceMode } from '../models/persistence-node.model';

/** The longest table name the canvas caption shows whole; a longer one is cut to end in "…". */
export const CAPTION_TABLE_NAME_LIMIT = 20;

// The stripe colour per mode is PERSISTENCE_MODE_COLORS in @shared/models, shared with the session card.
export const PERSISTENCE_MODE_LABELS: Record<PersistenceMode, string> = {
    read: 'Read',
    write: 'Write',
    delete: 'Delete',
};

export function persistenceSubtitle(mode: PersistenceMode, tableName: string | null, keyCount: number): string {
    const keys = `${keyCount} ${keyCount === 1 ? 'key' : 'keys'}`;
    return `${PERSISTENCE_MODE_LABELS[mode]} · ${tableName ?? 'no table'} · ${keys}`;
}

/** The subtitle for the caption under the node, its table name cut to CAPTION_TABLE_NAME_LIMIT. */
export function persistenceCaption(mode: PersistenceMode, tableName: string | null, keyCount: number): string {
    const shownName = tableName === null ? null : truncateName(tableName, CAPTION_TABLE_NAME_LIMIT);
    return persistenceSubtitle(mode, shownName, keyCount);
}
