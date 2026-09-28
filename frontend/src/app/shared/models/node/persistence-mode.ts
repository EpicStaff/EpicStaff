export type PersistenceMode = 'read' | 'write' | 'delete';

/** The mode stripe on the canvas node and the session card; everything else keeps NODE_COLORS[PERSISTENCE]. */
export const PERSISTENCE_MODE_COLORS: Record<PersistenceMode, string> = {
    read: 'var(--success-color)',
    write: 'var(--color-status-processing)',
    delete: 'var(--color-status-error)',
};
