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

export type UnnumberedSnapshotNodeType = keyof typeof UNNUMBERED_SNAPSHOT_NODE_TYPES;

const UNNUMBERED_NODE_TYPES: ReadonlySet<NodeType> = new Set(Object.values(UNNUMBERED_SNAPSHOT_NODE_TYPES));

/** Whether nodes of `type` get a number from the graph's counter. */
export function isNumberedNodeType(type: NodeType): boolean {
    return !UNNUMBERED_NODE_TYPES.has(type);
}

/** Whether nodes an export or snapshot tags `nodeType` get a number from the graph's counter. */
export function isNumberedSnapshotNodeType(nodeType: SnapshotNodeType): boolean {
    return !Object.hasOwn(UNNUMBERED_SNAPSHOT_NODE_TYPES, nodeType);
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
