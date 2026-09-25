export type PersistenceMode = 'read' | 'write' | 'delete';

/**
 * A read or write entry. Read writes the stored value of `key` into the flow state path `value`
 * (None when the key is missing); write stores the value at the state path `value`, which may end
 * in `|default`.
 */
export interface PersistenceValueEntry {
    key: string;
    value: string;
}

export interface PersistenceDeleteEntry {
    key: string;
}

export type PersistenceEntry = PersistenceValueEntry | PersistenceDeleteEntry;

export interface PersistenceNodeData {
    persistence_table: number | null;
    mode: PersistenceMode;
    entries: PersistenceEntry[];
}

export interface GetPersistenceNodeRequest extends PersistenceNodeData {
    id: number;
    graph: number;
    node_name: string;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
    content_hash?: string;
}
