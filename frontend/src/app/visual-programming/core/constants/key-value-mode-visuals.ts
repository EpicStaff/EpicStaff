import { truncateName } from '../../utils/surface/surface-collection-conflict.util';
import { KeyValueMode } from '../models/key-value-node.model';

/** The longest table name the canvas caption shows whole; a longer one is cut to end in "…". */
export const CAPTION_TABLE_NAME_LIMIT = 20;

// The stripe colour per mode is KEY_VALUE_MODE_COLORS in @shared/models, shared with the session card.
export const KEY_VALUE_MODE_LABELS: Record<KeyValueMode, string> = {
    read: 'Read',
    write: 'Write',
    delete: 'Delete',
};

export function keyValueSubtitle(mode: KeyValueMode, tableName: string | null, keyCount: number): string {
    const keys = `${keyCount} ${keyCount === 1 ? 'key' : 'keys'}`;
    return `${KEY_VALUE_MODE_LABELS[mode]} · ${tableName ?? 'no table'} · ${keys}`;
}

/** The subtitle for the caption under the node, its table name cut to CAPTION_TABLE_NAME_LIMIT. */
export function keyValueCaption(mode: KeyValueMode, tableName: string | null, keyCount: number): string {
    const shownName = tableName === null ? null : truncateName(tableName, CAPTION_TABLE_NAME_LIMIT);
    return keyValueSubtitle(mode, shownName, keyCount);
}
