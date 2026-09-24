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

export interface PersistenceTableEntry {
    id: number;
    table: number;
    key: string;
    value: unknown;
    created_at: string;
    updated_at: string;
    updated_by_session: number | null;
    updated_by_graph: number | null;
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

export interface PersistenceEntriesQuery {
    table: number;
    search: string;
    limit: number;
    offset: number;
}
