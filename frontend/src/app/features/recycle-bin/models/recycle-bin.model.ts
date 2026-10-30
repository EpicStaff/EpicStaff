import { NodeListItem } from '@shared/components';
import { ActionCode, ResourceCode, UserSummary } from '@shared/models';

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

/** One backend bin endpoint family; every one has a paged list and `{ids}` bulk bodies. */
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

/** What the frontend needs to know about one source. */
export interface RecycleBinSourceDefinition {
    /** List URL relative to the API root; the bin endpoints hang off it. */
    path: string;
}

/** A resource source's rows all share one kind; storage rows take theirs from `item_type` (STORAGE_ITEM_KINDS). */
export interface RecycleBinResourceSourceDefinition extends RecycleBinSourceDefinition {
    /** The Kind column label: "Flow", "Python tool", … */
    kind: string;
    /** Names the source as a whole: the Tools tab's Kind switch ("Python tools") and its empty list. */
    pluralKind: string;
}

/** Every source once: a resource source without `kind`, or a missing source, does not compile. */
export type RecycleBinSourceDefinitions = Record<RecycleBinResourceSourceKey, RecycleBinResourceSourceDefinition> &
    Record<'storage', RecycleBinSourceDefinition>;

export interface RecycleBinTabDefinition {
    key: RecycleBinTabKey;
    label: string;
    resource: ResourceCode;
    /**
     * The bins this tab shows, one at a time. Tools has two (Python + MCP): its Kind filter switches
     * between them, the first by default.
     */
    sources: readonly RecycleBinSourceKey[];
    /** Plural used in the empty state: "Deleted flows stay here for 7 days." */
    pluralNoun: string;
    /** A column with each row's `contentsTotal` (a flow's nodes, an agent's own surfaces). */
    countColumn?: { label: string };
}

export type CanFunction = (resource: ResourceCode, action: ActionCode) => boolean;

// API shapes (snake_case, as the backend sends them)

/** Every content of one binned item ("Show all"); the list sends at most 100. */
export interface GetRecycleBinContentsResponse {
    contents: GetRecycleBinContentResponse[];
    hidden_contents: GetRecycleBinHiddenContentsResponse[];
    contents_total: number;
}

export interface GetRecycleBinContentResponse {
    /** Can be blank (decision-table nodes). For a storage folder: the path relative to the folder. */
    name: string;
    /** A frontend NodeType value for flow nodes; otherwise one of RecycleBinContentKind. */
    kind: string;
}

/**
 * Contents of one kind the user may not read the names of, only counted. One per kind, `count` at least 1;
 * storage never has any.
 */
export interface GetRecycleBinHiddenContentsResponse {
    /** Same values as GetRecycleBinContentResponse.kind. */
    kind: string;
    count: number;
}

/**
 * `notice` is text the UI highlights (the item won't come back quite as it was); `user` is a person
 * ("Created by", "Deleted by").
 */
export type RecycleBinDetailFormat = 'text' | 'date' | 'size' | 'notice' | 'user';

/**
 * One line of basic info. Every field of the tab is sent, in a fixed order, and long text whole; every tab
 * starts with "Created by" and "Deleted by".
 */
export type GetRecycleBinDetailResponse =
    | {
          label: string;
          /** Text, an ISO 8601 date or a size in bytes, per `format`; null when the field is empty. */
          value: string | number | null;
          format: Exclude<RecycleBinDetailFormat, 'user'>;
      }
    | {
          label: string;
          /** Null when the user is unknown (never recorded, or no longer in the organization). */
          value: UserSummary | null;
          format: 'user';
      };

export interface GetRecycleBinEntryResponse {
    id: number;
    name: string;
    /** ISO 8601 */
    deleted_at: string;
    days_left: number;
    details: GetRecycleBinDetailResponse[];
    /** At most 100, only the ones the user may read; `contents_total` has the full count. */
    contents: GetRecycleBinContentResponse[];
    hidden_contents: GetRecycleBinHiddenContentsResponse[];
    /** Every content, hidden ones included. */
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

/** Every `GET <list>/recycle-bin/` is paged with limit/offset. */
export interface GetRecycleBinPageResponse<Entry extends GetRecycleBinEntryResponse = GetRecycleBinEntryResponse> {
    count: number;
    next: string | null;
    previous: string | null;
    results: Entry[];
}

export interface RestoreRecycleBinItemResponse {
    id: number;
    name: string;
    renamed_from: string | null;
    /** Whether everything that used the item is connected again (it kept its links in the bin). */
    links_restored: boolean;
}

// View models (camelCase)

export interface RecycleBinItem {
    /** Unique within a tab: `${source}-${id}`. Python and MCP tool ids can collide, and Tools shows both bins. */
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
    /** How many contents the user may not read the names of; never listed. */
    hiddenContentsCount: number;
    /**
     * How many items the restore brings back in all, hidden ones included; more than `contents.length` plus
     * `hiddenContentsCount` when the list was capped.
     */
    contentsTotal: number;
}

/** A detail with its value already in the type its format needs; the table formats it for display. */
export type RecycleBinDetail =
    | { label: string; format: 'text'; value: string }
    | { label: string; format: 'date'; value: Date }
    | { label: string; format: 'size'; value: number }
    /** How it comes back: without something, or differently (shared). Accent colour, no icon. */
    | { label: string; format: 'notice'; value: string }
    /** A person with their avatar; null is an unknown user, shown as a muted "Unknown". */
    | { label: string; format: 'user'; value: UserSummary | null }
    /** The field is empty; shown as a muted dash so every row of a tab has the same lines. */
    | { label: string; format: 'empty'; value: null };

export interface RecycleBinRestoreOutcome {
    /** Which bin it came from: a renamed secret needs a note, since code reads secrets by name. */
    source: RecycleBinSourceKey;
    name: string;
    renamedFrom: string | null;
    /** Everything that used it is connected again; otherwise it came back without its links. */
    linksRestored: boolean;
}

export type RecycleBinLoadStatus = 'loading' | 'loaded' | 'error';

/** Where the tab's paged list stands. */
export interface RecycleBinPage {
    /** 1-based. */
    current: number;
    size: number;
    totalCount: number;
}

// Bulk actions: every bin takes `{ids}` (1–100) on `<list>/recycle-bin/restore|purge/`. Emptying
// every bin at once is its own endpoint (`recycle-bin/empty/`).

export type RecycleBinSelection = { ids: number[] };

export interface RecycleBinBulkFailureResponse {
    id: number;
    name: string;
    message: string;
}

/** POST recycle-bin/empty/ (superadmin only): one slice of every bin; call again while `remaining`. */
export interface RecycleBinEmptyResponse {
    purged_count: number;
    /** Items still in those bins: left for the next call, or ones that failed. */
    remaining: number;
    failed: (RecycleBinBulkFailureResponse & { source: RecycleBinSourceKey })[];
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

/** "Empty recycle bin": what it deleted and skipped, and what it left without trying. */
export interface RecycleBinEmptyResult extends RecycleBinPurgeResult {
    /** Items still in the bin besides the failed ones: emptying stopped when a call deleted nothing. */
    leftCount: number;
}

// Search and sort

export type RecycleBinSortField = 'deletedAt' | 'daysLeft';
export type RecycleBinSortDirection = 'asc' | 'desc';

export interface RecycleBinSort {
    field: RecycleBinSortField;
    direction: RecycleBinSortDirection;
}

/** The count column's filter, sent as `contents`: items with some contents, or none. */
export type RecycleBinContentsFilter = 'some' | 'none';

/** Server-side query of a bin list (`search` matches the item's own name). */
export interface RecycleBinListQuery {
    search: string;
    /** `-deleted_at` (default), `deleted_at`, `days_left` or `-days_left`. */
    ordering: string;
    /** The count column's filter; `null` for all. Only tabs with a count column set it. */
    contents: RecycleBinContentsFilter | null;
    /** Files only: the `item_type` filter; `null` for both files and folders. Other sources ignore it. */
    itemType: GetStorageRecycleBinEntryResponse['item_type'] | null;
}

/** An option of a column filter: a source key (Tools) or storage item type (Kind), or a count (Nodes / Surfaces). */
export interface RecycleBinFilterOption {
    name: string;
    value: string;
}
