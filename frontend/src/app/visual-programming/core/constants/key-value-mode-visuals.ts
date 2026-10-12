import { truncateName } from '../../utils/surface/surface-collection-conflict.util';
import { KeyValueMode } from '../models/key-value-node.model';

/** The longest table name the #N tab above the node shows whole; a longer one is cut to end in "…". */
export const CAPTION_TABLE_NAME_LIMIT = 20;

// The stripe colour per mode is KEY_VALUE_MODE_COLORS in @shared/models, shared with the session card.
export const KEY_VALUE_MODE_LABELS: Record<KeyValueMode, string> = {
    read: 'Read',
    write: 'Write',
    delete: 'Delete',
};

/** A Key-Value node's summary as [mode, table, "N keys"]; given a limit, a longer table name is cut to end in "…". */
export function keyValueSummaryParts(
    mode: KeyValueMode,
    tableName: string | null,
    keyCount: number,
    tableNameLimit?: number
): string[] {
    const shownTableName = tableName !== null && tableNameLimit ? truncateName(tableName, tableNameLimit) : tableName;
    const keys = `${keyCount} ${keyCount === 1 ? 'key' : 'keys'}`;
    return [KEY_VALUE_MODE_LABELS[mode], shownTableName ?? 'no table', keys];
}
