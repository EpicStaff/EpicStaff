import { NodeType } from '../enums/node-type';
import { NODE_TYPE_PREFIXES } from '../enums/node-type-prefixes';

/**
 * Generate a display name for a node using the node's sequential badge number.
 * @param type NodeType
 * @param nodeNumber The sequential badge number assigned to this node
 */
export function generateNodeDisplayName(type: NodeType, nodeNumber?: number): string {
    if (type === NodeType.END) {
        return '__end_node__';
    }
    if (type === NodeType.START) {
        return 'Start';
    }
    const prefix = NODE_TYPE_PREFIXES[type] || 'Node';
    return nodeNumber != null ? `${prefix} #${nodeNumber}` : prefix;
}

/**
 * Generate display names for multiple nodes at once using their assigned sequential badge numbers.
 * @param nodesToCreate Array of nodes to create with their types
 * @param nodeNumbers Sequential badge numbers for each node (same order as nodesToCreate)
 * @returns Array of display names in the same order as nodesToCreate
 */
export function generateMultipleNodeDisplayNames(
    nodesToCreate: Array<{ type: NodeType }>,
    nodeNumbers: number[]
): string[] {
    return nodesToCreate.map((node, index) => generateNodeDisplayName(node.type, nodeNumbers[index]));
}
