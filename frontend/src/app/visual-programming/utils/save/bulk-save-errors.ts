import { ApiErrorDetail } from '@shared/models';

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

/** A place in a sent list, as an `attr` path names it. */
const LIST_POSITION = /^\d+$/;

/** The child lists whose rows the editor tells apart, and how `buildBulkSavePayload` names a sent row. */
const CHILD_ROW_KEY: Readonly<Record<string, (row: Record<string, unknown>) => unknown>> = {
    tasks: (task) => task['id'] ?? task['temp_id'],
    prompt_configs: (prompt) => prompt['prompt_key'],
};

/** Where on a canvas node an error goes: a field of the node, or of one of its child rows; null for the whole. */
interface ErrorTarget {
    readonly field: string | null;
    readonly child?: SaveErrorChildRow;
    readonly sentValue?: unknown;
}

/** The key a save error carries for this agent task: its `id` once saved, its `tempId` before (as the payload sends it). */
export function agentTaskSaveErrorKey(task: Pick<AgentNodeTaskUi, 'id' | 'tempId'>): string {
    return String(task.id ?? task.tempId);
}

/**
 * Places the errors of a refused bulk save on the canvas nodes the payload sent. An error's `attr` names the item
 * as `<list key>.<index>` in the sent payload, then the field (`task_node_list.3.instructions`): a created item is
 * found by its `temp_id` (the canvas id), an updated one by its `id` (backend node ids are unique across node
 * tables). A deeper path counts for its first field, except in an agent's `tasks` or a classification table's
 * `prompt_configs`, where the error keeps the row (`agent_node_list.0.tasks.1.name`). The messages of whatever
 * cannot be placed come back as `unplaced`: errors of edges, of the graph as a whole, of an item no canvas node
 * matches.
 */
export function mapBulkSaveErrors(
    payload: Record<string, unknown>,
    errors: readonly ApiErrorDetail[],
    nodes: readonly NodeModel[]
): MappedSaveErrors {
    const byNodeId = new Map<string, SaveFieldError[]>();
    const unplaced: string[] = [];

    for (const { detail, attr } of errors) {
        if (!detail.trim()) continue;
        const placed = attr === null ? null : placeError(attr.split('.'), payload, nodes);
        if (placed) {
            byNodeId.set(placed.nodeId, withMessage(byNodeId.get(placed.nodeId) ?? [], placed.target, detail));
        } else {
            unplaced.push(detail);
        }
    }
    return { byNodeId, unplaced };
}

/** The canvas node an error's `attr` path is about, and where on it; null when no canvas node matches it. */
function placeError(
    path: readonly string[],
    payload: Record<string, unknown>,
    nodes: readonly NodeModel[]
): { nodeId: string; target: ErrorTarget } | null {
    const [listKey, position, ...fieldPath] = path;
    const items = payload[listKey];
    if (!NODE_LIST_KEYS.has(listKey) || !Array.isArray(items) || !isListPosition(position)) return null;
    const item: unknown = items[Number(position)];
    if (!isRecord(item)) return null;
    const nodeId = canvasNodeIdOf(item, nodes);
    return nodeId === null ? null : { nodeId, target: targetIn(item, fieldPath) };
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

function targetIn(item: Record<string, unknown>, fieldPath: readonly string[]): ErrorTarget {
    const [field, rowPosition, rowField] = fieldPath;
    if (field === undefined || field === NON_FIELD_ERRORS) return { field: null };
    return childRowTarget(field, item[field], rowPosition, rowField) ?? { field, sentValue: item[field] };
}

/** A field of a sent child row; null when `list` has no rows the editor tells apart, or the row is not found. */
function childRowTarget(
    list: string,
    sentRows: unknown,
    rowPosition: string | undefined,
    rowField: string | undefined
): ErrorTarget | null {
    const rowKeyOf = CHILD_ROW_KEY[list];
    if (!rowKeyOf || !Array.isArray(sentRows) || !isListPosition(rowPosition)) return null;

    const position = Number(rowPosition);
    const row: unknown = sentRows[position];
    if (!isRecord(row)) return null;
    const key = rowKeyOf(row);
    if (typeof key !== 'string' && typeof key !== 'number') return null;

    const child: SaveErrorChildRow = { list, key: String(key), position };
    return rowField === undefined || rowField === NON_FIELD_ERRORS
        ? { field: null, child }
        : { field: rowField, child, sentValue: row[rowField] };
}

/** The node's errors with `message` added to those of the same place, or as a new place after them. */
function withMessage(fieldErrors: SaveFieldError[], target: ErrorTarget, message: string): SaveFieldError[] {
    const index = fieldErrors.findIndex((fieldError) => isSamePlace(fieldError, target));
    if (index === -1) {
        const { field, child, sentValue } = target;
        return [
            ...fieldErrors,
            { field, ...(child ? { child } : {}), ...(field !== null ? { sentValue } : {}), messages: [message] },
        ];
    }
    return fieldErrors.map((fieldError, at) =>
        at === index ? { ...fieldError, messages: [...fieldError.messages, message] } : fieldError
    );
}

function isSamePlace(fieldError: SaveFieldError, target: ErrorTarget): boolean {
    return (
        fieldError.field === target.field &&
        fieldError.child?.list === target.child?.list &&
        fieldError.child?.position === target.child?.position
    );
}

function isListPosition(segment: string | undefined): segment is string {
    return segment !== undefined && LIST_POSITION.test(segment);
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
