import { NodeType } from '@shared/models';

/** Node types the backend never numbers: they carry no #N badge. */
const UNNUMBERED_NODE_TYPES: ReadonlySet<NodeType> = new Set([NodeType.START, NodeType.END, NodeType.NOTE]);

/** Whether nodes of `type` get a number from the graph's counter. */
export function isNumberedNodeType(type: NodeType): boolean {
    return !UNNUMBERED_NODE_TYPES.has(type);
}
