import { NodeType } from '../enums/node-type';
import { NODE_TYPE_PREFIXES } from '../enums/node-type-prefixes';

/**
 * Generate a display name for a node using the node's sequential badge number.
 * @param type NodeType
 * @param data Optional node data (may contain name for PROJECT)
 * @param nodeNumber The sequential badge number assigned to this node
 */
export function generateNodeDisplayName(type: NodeType, data: unknown, nodeNumber: number): string {
    if (type === NodeType.END) {
        return '__end_node__';
    }
    if (type === NodeType.PROJECT) {
        const projectName = (data as { name?: string } | null)?.name || 'My Project';
        return `${projectName} #${nodeNumber}`;
    }
    const prefix = NODE_TYPE_PREFIXES[type] || 'Node';
    return `${prefix} #${nodeNumber}`;
}

/**
 * Generate display names for multiple nodes at once using their assigned sequential badge numbers.
 * @param nodesToCreate Array of nodes to create with their types and data
 * @param nodeNumbers Sequential badge numbers for each node (same order as nodesToCreate)
 * @returns Array of display names in the same order as nodesToCreate
 */
export function generateMultipleNodeDisplayNames(
    nodesToCreate: Array<{ type: NodeType; data: unknown }>,
    nodeNumbers: number[]
): string[] {
    return nodesToCreate.map((node, index) => generateNodeDisplayName(node.type, node.data, nodeNumbers[index]));
}
