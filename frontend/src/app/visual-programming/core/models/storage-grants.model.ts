/** What one slot of a node's code may do with the flow's attached files, per kind of access. */
export interface StorageGrants {
    read: boolean;
    write: boolean;
    delete: boolean;
}

/** The grant columns of a node DTO that has one slot of code. Absent in a version snapshot older than grants. */
export interface StorageGrantFields {
    storage_grant_read?: boolean;
    storage_grant_write?: boolean;
    storage_grant_delete?: boolean;
}

/** The grant columns of a classification decision table, which has a pre-code and a post-code slot. */
export interface CdtStorageGrantFields {
    pre_storage_grant_read?: boolean;
    pre_storage_grant_write?: boolean;
    pre_storage_grant_delete?: boolean;
    post_storage_grant_read?: boolean;
    post_storage_grant_write?: boolean;
    post_storage_grant_delete?: boolean;
}

/** Which grant slot of a node: its only one, or a classification decision table's pre / post code. */
export type StorageGrantSlot = 'main' | 'pre' | 'post';
