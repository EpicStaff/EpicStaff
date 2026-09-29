export interface KeyValueTable {
    id: number;
    name: string;
    description: string;
    entry_count: number;
    created_at: string;
    updated_at: string;
}

export interface CreateKeyValueTableRequest {
    name: string;
    description?: string;
}

export type UpdateKeyValueTableRequest = Partial<CreateKeyValueTableRequest>;

// `GET key-value-tables/{id}/usage/`: the Key-Value nodes bound to the table, and the flows they are in.
export interface KeyValueTableUsage {
    node_count: number;
    flow_count: number;
}

// The full entry: `GET key-value-table-entries/{id}/` and the create / update responses.
export interface KeyValueTableEntry {
    id: number;
    table: number;
    key: string;
    value: unknown;
    created_at: string;
    updated_at: string;
    updated_by_session: number | null;
    updated_by_graph: number | null;
    updated_by_graph_name: string | null;
}

// A row of the entries list: no `value` (up to 256 KiB each), only the start of its JSON text.
export interface KeyValueTableEntryListItem extends Omit<KeyValueTableEntry, 'value'> {
    // The first 200 characters of the value as Postgres prints jsonb (`{"a": 1}`), not JSON.stringify.
    value_preview: string;
    value_truncated: boolean;
}

export interface CreateKeyValueTableEntryRequest {
    table: number;
    key: string;
    value: unknown;
}

export type UpdateKeyValueTableEntryRequest = Partial<Omit<CreateKeyValueTableEntryRequest, 'table'>>;

export interface KeyValueEntryLookup {
    exists: boolean;
    value_preview: string | null;
    updated_at: string | null;
}

export type KeyValueEntryLookupResponse = Record<string, KeyValueEntryLookup>;

export type KeyValueEntrySortField = 'key' | 'session' | 'updated_at';
// DRF-style `ordering` value: the field ascending, or `-field` descending.
export type KeyValueEntryOrdering = KeyValueEntrySortField | `-${KeyValueEntrySortField}`;

export interface KeyValueEntriesQuery {
    table: number;
    search: string;
    // Omitted: the server default (key ascending).
    ordering?: KeyValueEntryOrdering;
    limit: number;
    offset: number;
}
