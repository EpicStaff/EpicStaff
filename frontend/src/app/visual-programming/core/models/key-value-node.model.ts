import { KeyValueMode } from '@shared/models';

// Shared with the session card, which colours its stripe by mode too.
export type { KeyValueMode };

/**
 * A read or write entry. Read writes the stored value of `key` into the flow state path `value`
 * (None when the key is missing); write stores the value at the state path `value`, which may end
 * in `|default`.
 */
export interface KeyValueReadWriteEntry {
    key: string;
    value: string;
}

export interface KeyValueDeleteEntry {
    key: string;
}

export type KeyValueEntry = KeyValueReadWriteEntry | KeyValueDeleteEntry;

export interface KeyValueNodeData {
    key_value_table: number | null;
    mode: KeyValueMode;
    entries: KeyValueEntry[];
}

export interface GetKeyValueNodeRequest extends KeyValueNodeData {
    id: number;
    graph: number;
    node_name: string;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
    content_hash?: string;
}
