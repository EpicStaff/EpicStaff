export type KeyValueMode = 'read' | 'write' | 'delete';

/** The mode stripe on the canvas node and the session card; everything else keeps NODE_COLORS[KEY_VALUE]. */
export const KEY_VALUE_MODE_COLORS: Record<KeyValueMode, string> = {
    read: 'var(--success-color)',
    write: 'var(--color-status-processing)',
    delete: 'var(--color-status-error)',
};
