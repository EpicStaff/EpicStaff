import { GetStorageRecycleBinEntryResponse, RecycleBinSourceDefinitions } from '../models/recycle-bin.model';

/** Every source of the bin, once. Adding a source means one entry here (the type requires it). */
export const RECYCLE_BIN_SOURCES: RecycleBinSourceDefinitions = {
    storage: { path: 'storage/' },
    flow: { path: 'graphs/', kind: 'Flow', pluralKind: 'Flows' },
    agent: { path: 'agent-definitions/', kind: 'Agent', pluralKind: 'Agents' },
    surface: { path: 'surfaces/', kind: 'Surface', pluralKind: 'Surfaces' },
    python_tool: { path: 'python-code-tool/', kind: 'Python tool', pluralKind: 'Python tools' },
    mcp_tool: { path: 'mcp-tools/', kind: 'MCP tool', pluralKind: 'MCP tools' },
    collection: { path: 'source-collections/', kind: 'Collection', pluralKind: 'Collections' },
    key_value_table: { path: 'key-value-tables/', kind: 'Key-value table', pluralKind: 'Key-value tables' },
    secret: { path: 'secrets/', kind: 'Secret', pluralKind: 'Secrets' },
    realtime_channel: { path: 'realtime-channels/', kind: 'Voice channel', pluralKind: 'Voice channels' },
    webhook_trigger: { path: 'webhook-triggers/', kind: 'Webhook trigger', pluralKind: 'Webhook triggers' },
};

/** Kinds of the storage rows, by `item_type`. */
export const STORAGE_ITEM_KINDS: Record<GetStorageRecycleBinEntryResponse['item_type'], string> = {
    file: 'File',
    folder: 'Folder',
};

/** "Show all" loads at most this many items of a row (the backend's SHOW_ALL_LIMIT); past it, "and N more". */
export const RECYCLE_BIN_SHOW_ALL_LIMIT = 5000;

/** Rows per page of every bin list. Matches the backend's default page size (it takes at most 100). */
export const RECYCLE_BIN_PAGE_SIZE = 50;

/** The bulk endpoints take at most this many ids per call; larger selections are sent in chunks. */
export const RECYCLE_BIN_BULK_ID_LIMIT = 100;
