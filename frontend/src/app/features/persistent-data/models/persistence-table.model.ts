export interface PersistenceTable {
    id: number;
    name: string;
    description: string;
    entry_count: number;
    created_at: string;
    updated_at: string;
}

export interface CreatePersistenceTableRequest {
    name: string;
    description?: string;
}

export type UpdatePersistenceTableRequest = Partial<CreatePersistenceTableRequest>;

// The full entry: `GET persistence-table-entries/{id}/` and the create / update responses.
export interface PersistenceTableEntry {
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
export interface PersistenceTableEntryListItem extends Omit<PersistenceTableEntry, 'value'> {
    // The first 200 characters of the value as Postgres prints jsonb (`{"a": 1}`), not JSON.stringify.
    value_preview: string;
    value_truncated: boolean;
}

export interface CreatePersistenceTableEntryRequest {
    table: number;
    key: string;
    value: unknown;
}

export type UpdatePersistenceTableEntryRequest = Partial<Omit<CreatePersistenceTableEntryRequest, 'table'>>;

export interface PersistenceEntryLookup {
    exists: boolean;
    value_preview: string | null;
    updated_at: string | null;
}

export type PersistenceEntryLookupResponse = Record<string, PersistenceEntryLookup>;

export type PersistenceEntrySortField = 'key' | 'session' | 'updated_at';
// DRF-style `ordering` value: the field ascending, or `-field` descending.
export type PersistenceEntryOrdering = PersistenceEntrySortField | `-${PersistenceEntrySortField}`;

export interface PersistenceEntriesQuery {
    table: number;
    search: string;
    // Omitted: the server default (key ascending).
    ordering?: PersistenceEntryOrdering;
    limit: number;
    offset: number;
}
