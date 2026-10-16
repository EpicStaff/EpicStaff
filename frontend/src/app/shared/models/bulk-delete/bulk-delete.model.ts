import { Observable } from 'rxjs';

/** Largest number of ids a single bulk-delete group may send in one request. */
export const BULK_DELETE_MAX_IDS = 500;

export type BulkDeleteSkipReason = 'in_use_restricted' | 'protected';

export type BulkDeleteUsageKind = 'flow' | 'agent' | 'agent_definition' | 'crew' | 'collection';

export interface BulkDeleteUsageRef {
    resource_type: string;
    kind: BulkDeleteUsageKind;
    id: number;
    name: string | null;
}

export interface BulkDeleteUsageBucket {
    resource_type: string;
    visible_count: number;
    visible_sample: BulkDeleteUsageRef[];
    truncated: boolean;
}

export interface BulkDeleteUsageReport {
    blocked: boolean;
    by_resource_type: BulkDeleteUsageBucket[];
}

export interface BulkDeleteSkippedEntry {
    id: number;
    reason: BulkDeleteSkipReason;
}

export interface BulkDeleteResponse {
    dry_run: boolean;
    deleted_count: number;
    deleted_ids: number[];
    deletable_ids: number[];
    not_found_ids: number[];
    skipped: BulkDeleteSkippedEntry[];
    /** Keyed by entity id as a string; filled on dry run only, `{}` on a real delete. */
    usage: Record<string, BulkDeleteUsageReport>;
}

export interface BulkDeleteOptions {
    dryRun?: boolean;
}

/** Implemented by a storage service (or a component that owns its list). */
export interface BulkDeleteTarget {
    previewBulkDelete(ids: number[]): Observable<BulkDeleteResponse>;
    /** Real delete; must drop `deleted_ids ∪ not_found_ids` from its cache. */
    bulkDelete(ids: number[]): Observable<BulkDeleteResponse>;
    removeFromCache(ids: number[]): void;
}

export interface BulkDeleteLabel {
    singular: string;
    plural: string;
}

export interface BulkDeleteItem {
    id: number;
    name: string;
}

/** Present on a group whose items move to the recycle bin instead of being deleted for good. */
export interface BulkDeleteRecycleBin {
    /** How long a binned item stays restorable; `null` while the setting is not loaded. */
    retentionDays: number | null;
}

export interface BulkDeleteGroup {
    target: BulkDeleteTarget;
    label: BulkDeleteLabel;
    items: BulkDeleteItem[];
    recycleBin?: BulkDeleteRecycleBin;
}

export interface BulkDeleteOutcome {
    group: BulkDeleteGroup;
    response?: BulkDeleteResponse;
    error?: unknown;
}

// Dialog view model

export interface BulkDeleteUsageLine {
    label: string;
    count: number;
    sampleNames: string[];
    hasMore: boolean;
}

export interface BulkDeletePreviewItem {
    id: number;
    name: string;
    usage: BulkDeleteUsageLine[];
}

export interface BulkDeletePreviewGroup {
    label: BulkDeleteLabel;
    recycleBin?: BulkDeleteRecycleBin;
    deletable: BulkDeletePreviewItem[];
    blocked: BulkDeleteItem[];
    notFound: BulkDeleteItem[];
}
