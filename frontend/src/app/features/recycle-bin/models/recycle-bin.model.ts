import { NodeListItem } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';

export type RecycleBinTabKey =
    | 'flows'
    | 'agents'
    | 'surfaces'
    | 'tools'
    | 'files'
    | 'knowledge-sources'
    | 'key-value-tables'
    | 'secrets'
    | 'voice-channels'
    | 'webhook-triggers';

/** One backend bin endpoint family. `storage` is the only one with `{ids}` bodies and a paged list. */
export type RecycleBinSourceKey =
    | 'flow'
    | 'agent'
    | 'surface'
    | 'python_tool'
    | 'mcp_tool'
    | 'collection'
    | 'key_value_table'
    | 'secret'
    | 'realtime_channel'
    | 'webhook_trigger'
    | 'storage';

/** Every source that uses `<list URL>recycle-bin/`, `<id>/restore/`, `<id>/purge/`. */
export type RecycleBinResourceSourceKey = Exclude<RecycleBinSourceKey, 'storage'>;

export interface RecycleBinTabDefinition {
    key: RecycleBinTabKey;
    label: string;
    resource: ResourceCode;
    /** Lists merged into this tab. Tools has two (Python + MCP). */
    sources: readonly RecycleBinSourceKey[];
    /** Plural used in the empty state: "Deleted flows stay here for 7 days." */
    pluralNoun: string;
    /** A column with each row's `contentsTotal` (a flow's nodes, an agent's own surfaces). */
    countColumn?: { label: string };
}

export type CanFunction = (resource: ResourceCode, action: ActionCode) => boolean;

// API shapes (snake_case, as the backend sends them)

/** One thing a restore brings back with its entry. */
/** Every content of one binned item ("Show all"); the list sends at most 100. */
export interface GetRecycleBinContentsResponse {
    contents: GetRecycleBinContentResponse[];
    contents_total: number;
}

export interface GetRecycleBinContentResponse {
    /** Can be blank (decision-table nodes). For a storage folder: the path relative to the folder. */
    name: string;
    /** A frontend NodeType value for flow nodes; otherwise one of RecycleBinContentKind. */
    kind: string;
}

/** `warning` is text the UI highlights (the item won't come back quite as it was). */
export type RecycleBinDetailFormat = 'text' | 'date' | 'size' | 'notice';

/** One line of basic info. Every field of the tab is sent, in a fixed order, and long text whole. */
export interface GetRecycleBinDetailResponse {
    label: string;
    /** Text, an ISO 8601 date or a size in bytes, per `format`; null when the field is empty. */
    value: string | number | null;
    format: RecycleBinDetailFormat;
}

export interface GetRecycleBinEntryResponse {
    id: number;
    name: string;
    /** ISO 8601 */
    deleted_at: string;
    days_left: number;
    details: GetRecycleBinDetailResponse[];
    /** At most 100; `contents_total` has the full count. */
    contents: GetRecycleBinContentResponse[];
    contents_total: number;
}

/** Content kinds of the non-flow sources. */
export type RecycleBinContentKind =
    | 'surface'
    | 'python_tool'
    | 'mcp_tool'
    | 'knowledge_source'
    | 'file'
    | 'folder'
    | 'document';

export interface GetStorageRecycleBinEntryResponse extends GetRecycleBinEntryResponse {
    /** Full org-relative path; folders end in "/". */
    name: string;
    item_type: 'file' | 'folder';
}

/** `GET storage/recycle-bin/` is paged with limit/offset. */
export interface GetStorageRecycleBinPageResponse {
    count: number;
    next: string | null;
    previous: string | null;
    results: GetStorageRecycleBinEntryResponse[];
}

export interface RestoreRecycleBinItemResponse {
    id: number;
    name: string;
    renamed_from: string | null;
}

// View models (camelCase)

export interface RecycleBinItem {
    /** Unique within a tab: `${source}-${id}`. Python and MCP tool ids can collide in the Tools tab. */
    key: string;
    id: number;
    source: RecycleBinSourceKey;
    /** The full name; for storage the org-relative path. Used in dialogs and toasts. */
    name: string;
    /** What the row shows: for storage just the item's own name (`report.pdf`, `old/`); otherwise `name`. */
    displayName: string;
    /** "Flow", "Python tool", "MCP tool", "Folder", … */
    kind: string;
    deletedAt: Date;
    daysLeft: number;
    /** Basic info shown above the contents when the row is expanded. */
    details: RecycleBinDetail[];
    /** What the restore brings back with the item (at most 100). `nodeType` holds the content kind. */
    contents: NodeListItem[];
    /** How many items the restore brings back in all; more than `contents.length` when capped. */
    contentsTotal: number;
}

/** A detail with its value already in the type its format needs; the table formats it for display. */
export type RecycleBinDetail =
    | { label: string; format: 'text'; value: string }
    | { label: string; format: 'date'; value: Date }
    | { label: string; format: 'size'; value: number }
    /** How it comes back: without something, or differently (shared). Accent colour, no icon. */
    | { label: string; format: 'notice'; value: string }
    /** The field is empty; shown as a muted dash so every row of a tab has the same lines. */
    | { label: string; format: 'empty'; value: null };

export interface RecycleBinRestoreOutcome {
    /** Where it came from: whether what used it is connected again depends on it. */
    source: RecycleBinSourceKey;
    name: string;
    renamedFrom: string | null;
}

export type RecycleBinLoadStatus = 'loading' | 'loaded' | 'error';

/** Where the tab's list stands when the source is paged (only Files). */
export interface RecycleBinPage {
    /** 1-based. */
    current: number;
    size: number;
    totalCount: number;
}

// Bulk actions: every bin takes `{ids}` (1–100) or `{all: true}` on `<list>/recycle-bin/restore|purge/`.

export type RecycleBinSelection = { ids: number[] } | { all: true };

export interface RecycleBinBulkFailureResponse {
    id: number;
    name: string;
    message: string;
}

export interface RecycleBinBulkRestoreResponse {
    restored: RestoreRecycleBinItemResponse[];
    failed: RecycleBinBulkFailureResponse[];
}

export interface RecycleBinBulkPurgeResponse {
    purged: number[];
    failed: RecycleBinBulkFailureResponse[];
}

/** An item a bulk action skipped; the others went ahead. */
export interface RecycleBinFailure {
    name: string;
    message: string;
}

export interface RecycleBinRestoreResult {
    restored: RecycleBinRestoreOutcome[];
    failed: RecycleBinFailure[];
}

export interface RecycleBinPurgeResult {
    purgedCount: number;
    failed: RecycleBinFailure[];
}

// Search and sort

export type RecycleBinSortField = 'deletedAt' | 'daysLeft';
export type RecycleBinSortDirection = 'asc' | 'desc';

export interface RecycleBinSort {
    field: RecycleBinSortField;
    direction: RecycleBinSortDirection;
}

/** Server-side query of the paged Files list (`search` matches the item's own name). */
export interface RecycleBinStorageQuery {
    search: string;
    ordering: string;
    /** `item_type` filter; `null` for both files and folders. */
    itemType: GetStorageRecycleBinEntryResponse['item_type'] | null;
}

/** An option of a column filter: a source key or storage item type (Kind), or a count (Nodes / Surfaces). */
export interface RecycleBinFilterOption {
    name: string;
    value: string;
}

/** Client-side search, filters and sort of the lists that aren't paged. */
export interface RecycleBinListQuery {
    search: string;
    sort: RecycleBinSort;
    /** A source key (Tools); `null` for all. */
    kindFilter?: string | null;
    /** A RECYCLE_BIN_COUNT_RANGES value on `contentsTotal`; `null` for all. */
    countFilter?: string | null;
}
