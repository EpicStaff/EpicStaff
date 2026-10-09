import {
    GetStorageRecycleBinEntryResponse,
    RecycleBinResourceSourceKey,
    RecycleBinSourceKey,
} from '../models/recycle-bin.model';

/** List URL of each source, relative to the API root. The bin endpoints hang off it. */
export const RECYCLE_BIN_SOURCE_PATHS: Record<RecycleBinSourceKey, string> = {
    storage: 'storage/',
    flow: 'graphs/',
    agent: 'agent-definitions/',
    surface: 'surfaces/',
    python_tool: 'python-code-tool/',
    mcp_tool: 'mcp-tools/',
    collection: 'source-collections/',
    key_value_table: 'key-value-tables/',
    secret: 'secrets/',
    realtime_channel: 'realtime-channels/',
    webhook_trigger: 'webhook-triggers/',
};

export const RECYCLE_BIN_SOURCE_KINDS: Record<RecycleBinResourceSourceKey, string> = {
    flow: 'Flow',
    agent: 'Agent',
    surface: 'Surface',
    python_tool: 'Python tool',
    mcp_tool: 'MCP tool',
    collection: 'Collection',
    key_value_table: 'Key-value table',
    secret: 'Secret',
    realtime_channel: 'Voice channel',
    webhook_trigger: 'Webhook trigger',
};

export const STORAGE_ITEM_KINDS: Record<GetStorageRecycleBinEntryResponse['item_type'], string> = {
    file: 'File',
    folder: 'Folder',
};

/**
 * Sources whose items keep their links in the bin (the backend's soft_delete_keeps_references): a restore
 * connects back everything that used them. Any other item comes back without the links it had.
 */
export const RECYCLE_BIN_LINK_KEEPING_SOURCES: ReadonlySet<RecycleBinSourceKey> = new Set([
    'secret',
    'realtime_channel',
    'webhook_trigger',
]);

/** "Show all" loads at most this many items of a row (the backend's SHOW_ALL_LIMIT); past it, "and N more". */
export const RECYCLE_BIN_SHOW_ALL_LIMIT = 5000;

/** Rows per page of the Files tab, the only paged bin list. Matches the backend's default page size. */
export const RECYCLE_BIN_STORAGE_PAGE_SIZE = 50;

/** The bulk endpoints take at most this many ids per call; larger selections are sent in chunks. */
export const RECYCLE_BIN_BULK_ID_LIMIT = 100;
