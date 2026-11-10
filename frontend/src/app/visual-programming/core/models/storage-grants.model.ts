/**
 * What a node's code may do with the flow's attached files when no person started the run, per kind of access.
 * One slot's grants. All three `null` means "not configured" (a node saved before grants existed): the
 * legacy behaviour applies, and the values must go back to the server as they came.
 */
export interface StorageGrants {
    read: boolean | null;
    write: boolean | null;
    delete: boolean | null;
}

/** The grant columns of a node DTO that has one slot of code. */
export interface StorageGrantFields {
    storage_grant_read?: boolean | null;
    storage_grant_write?: boolean | null;
    storage_grant_delete?: boolean | null;
}

/** The grant columns of a classification decision table, which has a pre-code and a post-code slot. */
export interface CdtStorageGrantFields {
    pre_storage_grant_read?: boolean | null;
    pre_storage_grant_write?: boolean | null;
    pre_storage_grant_delete?: boolean | null;
    post_storage_grant_read?: boolean | null;
    post_storage_grant_write?: boolean | null;
    post_storage_grant_delete?: boolean | null;
}

/** Which grant slot of a node: its only one, or a classification decision table's pre / post code. */
export type StorageGrantSlot = 'main' | 'pre' | 'post';
