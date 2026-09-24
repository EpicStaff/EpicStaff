export type PersistenceMode = 'read' | 'write' | 'delete';

export interface PersistenceReadEntry {
    alias: string;
    key: string;
    default?: unknown;
}

export interface PersistenceWriteEntry {
    key: string;
    value: string;
}

export interface PersistenceDeleteEntry {
    key: string;
}

export type PersistenceEntry = PersistenceReadEntry | PersistenceWriteEntry | PersistenceDeleteEntry;

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
