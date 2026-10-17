import { NodeType } from '@shared/models';

import { SnapshotNodeType } from '../../../features/flows/models/graph-version-preview.model';
import { NodeModel } from '../models/node.model';

/**
 * Node types the backend never numbers: they carry no #N badge. Keyed by the `node_type` an export
 * or version snapshot writes, so snapshots and the canvas read the same rule.
 */
export const UNNUMBERED_SNAPSHOT_NODE_TYPES = {
    StartNode: NodeType.START,
    EndNode: NodeType.END,
    GraphNote: NodeType.NOTE,
} as const satisfies Partial<Record<SnapshotNodeType, NodeType>>;

const UNNUMBERED_NODE_TYPES: ReadonlySet<NodeType> = new Set(Object.values(UNNUMBERED_SNAPSHOT_NODE_TYPES));

/** Highest usable node number; mirrors the backend's MAX_BADGE_NUMBER. */
export const MAX_NODE_NUMBER = 1_000_000;

/** `value` when it is a usable node number (an integer in 1..MAX_NODE_NUMBER), else null. */
export function usableNodeNumberOrNull(value: unknown): number | null {
    return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= MAX_NODE_NUMBER
        ? value
        : null;
}

/** Whether nodes of `type` get a number from the graph's counter. */
export function isNumberedNodeType(type: NodeType): boolean {
    return !UNNUMBERED_NODE_TYPES.has(type);
}

/**
 * Moves every unsaved node (no `backendId`) that shows one of `takenNumbers` to `nextNumber()`, in
 * canvas order. A number the server gave a saved node is that node's; the unsaved node only showed
 * it as a guess the server never saw. Other nodes are returned as they are, same reference.
 */
export function renumberUnsavedNodesHolding(
    nodes: NodeModel[],
    takenNumbers: ReadonlySet<number>,
    nextNumber: () => number
): NodeModel[] {
    return nodes.map((node) =>
        node.backendId == null && node.nodeNumber != null && takenNumbers.has(node.nodeNumber)
            ? { ...node, nodeNumber: nextNumber() }
            : node
    );
}
