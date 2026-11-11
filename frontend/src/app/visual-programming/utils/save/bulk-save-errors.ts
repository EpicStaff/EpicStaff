import { AgentNodeTaskUi } from '../../core/models/agent-node.model';
import { NodeModel } from '../../core/models/node.model';
import { SNAPSHOT_NODE_LIST_KEY } from '../load/snapshot/map-snapshot-to-graph-dto';

/** A row of a node's child list that a save error is about. */
export interface SaveErrorChildRow {
    /** The child list's payload key: `tasks`, `prompt_configs`. */
    readonly list: string;
    /** How the sent row named itself (see {@link CHILD_ROW_KEY}). */
    readonly key: string;
    /** The row's place in the sent list, from 0. */
    readonly position: number;
}

/** What the backend refused in one field of a node a bulk save sent. */
export interface SaveFieldError {
    /** The payload key the messages are about (the row's own key for a child row); null for the node or row as a whole. */
    readonly field: string | null;
    readonly child?: SaveErrorChildRow;
    /** What the save sent in that field. */
    readonly sentValue?: unknown;
    readonly messages: readonly string[];
}

/** Save errors by canvas node id. */
export type SaveErrorsByNodeId = ReadonlyMap<string, readonly SaveFieldError[]>;

/** The errors of a refused bulk save: those placed on canvas nodes, and the messages of the rest. */
export interface MappedSaveErrors {
    readonly byNodeId: SaveErrorsByNodeId;
    /** What no canvas node takes: errors of edges, of the graph as a whole, of an item no canvas node matches. */
    readonly unplaced: readonly string[];
}

/** Every `GraphDto` node list; the payload's other arrays (`edge_list`) hold no nodes. */
const NODE_LIST_KEYS: ReadonlySet<string> = new Set(Object.values(SNAPSHOT_NODE_LIST_KEY));

/** DRF's key for an error about the item as a whole. */
const NON_FIELD_ERRORS = 'non_field_errors';

/** The child lists whose rows the editor tells apart, and how `buildBulkSavePayload` names a sent row. */
const CHILD_ROW_KEY: Readonly<Record<string, (row: Record<string, unknown>) => unknown>> = {
    tasks: (task) => task['id'] ?? task['temp_id'],
    prompt_configs: (prompt) => prompt['prompt_key'],
};

/** The key a save error carries for this agent task: its `id` once saved, its `tempId` before (as the payload sends it). */
export function agentTaskSaveErrorKey(task: Pick<AgentNodeTaskUi, 'id' | 'tempId'>): string {
    return String(task.id ?? task.tempId);
}

/**
 * Places the errors of a refused bulk save (`{<list key>: [{index, errors}]}`, `errors` a DRF detail or a plain
 * message) on the canvas nodes the payload sent at those indexes: a created item by its `temp_id` (the canvas id),
 * an updated one by its `id` (backend node ids are unique across node tables). Errors of an agent's `tasks` or a
 * classification table's `prompt_configs` rows keep the row. The messages of whatever cannot be placed come back
 * as `unplaced`: errors of an unknown shape, of edges, of the graph as a whole, of an item no canvas node matches.
 */
export function mapBulkSaveErrors(
    payload: Record<string, unknown>,
    errors: unknown,
    nodes: readonly NodeModel[]
): MappedSaveErrors {
    const byNodeId = new Map<string, SaveFieldError[]>();
    const unplaced: string[] = [];
    if (!isRecord(errors)) return { byNodeId, unplaced: collectMessages(errors) };

    for (const [listKey, itemErrors] of Object.entries(errors)) {
        const items = payload[listKey];
        if (!NODE_LIST_KEYS.has(listKey) || !Array.isArray(items) || !Array.isArray(itemErrors)) {
            unplaced.push(...collectMessages(itemErrors));
            continue;
        }

        for (const itemError of itemErrors) {
            const placed = placeItemError(itemError, items, nodes);
            if (!placed) {
                // The item's `index` is a number, which holds no message.
                unplaced.push(...collectMessages(itemError));
            } else if (placed.fieldErrors.length > 0) {
                byNodeId.set(placed.nodeId, [...(byNodeId.get(placed.nodeId) ?? []), ...placed.fieldErrors]);
            }
        }
    }
    return { byNodeId, unplaced };
}

/** The canvas node a node list's `{index, errors}` is about, and its errors; null when no canvas node matches it. */
function placeItemError(
    itemError: unknown,
    items: readonly unknown[],
    nodes: readonly NodeModel[]
): { nodeId: string; fieldErrors: SaveFieldError[] } | null {
    if (!isRecord(itemError) || typeof itemError['index'] !== 'number') return null;
    const item: unknown = items[itemError['index']];
    if (!isRecord(item)) return null;
    const nodeId = canvasNodeIdOf(item, nodes);
    return nodeId === null ? null : { nodeId, fieldErrors: toFieldErrors(item, itemError['errors']) };
}

function canvasNodeIdOf(item: Record<string, unknown>, nodes: readonly NodeModel[]): string | null {
    const tempId = item['temp_id'];
    const backendId = item['id'];
    const node =
        typeof tempId === 'string'
            ? nodes.find((candidate) => candidate.id === tempId)
            : typeof backendId === 'number'
              ? nodes.find((candidate) => candidate.backendId === backendId)
              : undefined;
    return node?.id ?? null;
}

function toFieldErrors(item: Record<string, unknown>, detail: unknown): SaveFieldError[] {
    if (!isRecord(detail)) return fieldError(null, undefined, detail);
    return Object.entries(detail).flatMap(([field, value]) => {
        if (field === NON_FIELD_ERRORS) return fieldError(null, undefined, value);
        return childRowErrors(field, item[field], value) ?? fieldError(field, item[field], value);
    });
}

/** Errors of a child list's rows, one DRF detail per sent row; null when `list` has no rows the editor tells apart. */
function childRowErrors(list: string, sentRows: unknown, value: unknown): SaveFieldError[] | null {
    const rowKeyOf = CHILD_ROW_KEY[list];
    if (!rowKeyOf || !Array.isArray(sentRows) || !Array.isArray(value)) return null;

    const leftOver: unknown[] = [];
    const rowErrors = value.flatMap((rowError: unknown, position) => {
        const row: unknown = sentRows[position];
        const key = isRecord(row) ? rowKeyOf(row) : null;
        if (!isRecord(rowError) || !isRecord(row) || (typeof key !== 'string' && typeof key !== 'number')) {
            leftOver.push(rowError);
            return [];
        }
        const child: SaveErrorChildRow = { list, key: String(key), position };
        return Object.entries(rowError).flatMap(([field, rowValue]) =>
            field === NON_FIELD_ERRORS
                ? fieldError(null, undefined, rowValue, child)
                : fieldError(field, row[field], rowValue, child)
        );
    });
    return [...rowErrors, ...fieldError(list, sentRows, leftOver)];
}

function fieldError(
    field: string | null,
    sentValue: unknown,
    value: unknown,
    child?: SaveErrorChildRow
): SaveFieldError[] {
    const messages = collectMessages(value);
    if (messages.length === 0) return [];
    return [{ field, ...(child ? { child } : {}), ...(field !== null ? { sentValue } : {}), messages }];
}

/** Every message in a DRF detail, however nested. */
function collectMessages(value: unknown): string[] {
    if (typeof value === 'string') return value.trim() ? [value] : [];
    if (Array.isArray(value)) return value.flatMap(collectMessages);
    if (isRecord(value)) return Object.values(value).flatMap(collectMessages);
    return [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
