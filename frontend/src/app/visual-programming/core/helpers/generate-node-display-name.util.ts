import { NodeType } from '../enums/node-type';
import { NODE_TYPE_PREFIXES } from '../enums/node-type-prefixes';
import { NodeModel } from '../models/node.model';

/**
 * Generate a display name for a node, following the same rules as onAddNodeFromContextMenu.
 * @param type NodeType
 * @param data Optional node data (may contain name for PROJECT)
 * @param currentNodes All current nodes in the flow (for counting)
 */
export function generateNodeDisplayName(type: NodeType, data: unknown, currentNodes: NodeModel[]): string {
    if (type === NodeType.END) {
        return '__end_node__';
    }
    if (type === NodeType.PROJECT) {
        const projectName = (data as { name?: string } | null)?.name || 'My Project';
        const count = getNextAvailableNumber(currentNodes, type, projectName);
        return `${projectName} (#${count})`;
    } else {
        const prefix = NODE_TYPE_PREFIXES[type] || 'Node';
        const count = getNextAvailableNumber(currentNodes, type, prefix);
        return `${prefix} (#${count})`;
    }
}

/**
 * Find the next available number for a node type, accounting for gaps in numbering.
 * @param currentNodes All current nodes in the flow
 * @param type NodeType to find number for
 * @param namePrefix The prefix to match against (e.g., "Agent-Node" or "My Project")
 * @returns Next available number
 */
function getNextAvailableNumber(currentNodes: NodeModel[], type: NodeType, namePrefix: string): number {
    // Get all existing node names of this type (filter out undefined for nodes like GraphNote that lack node_name)
    const existingNames = currentNodes
        .filter((n) => n.type === type)
        .map((n) => n.node_name)
        .filter((name): name is string => !!name);

    // Extract numbers from existing names that match our prefix pattern
    const usedNumbers = new Set<number>();

    existingNames.forEach((name) => {
        // Match pattern like "Agent-Node (#1)" or "My Project (#2)"
        const match = name.match(new RegExp(`^${namePrefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\(#(\\d+)\\)$`));
        if (match) {
            const number = parseInt(match[1], 10);
            usedNumbers.add(number);
        }
    });

    // Find the first available number starting from 1
    let nextNumber = 1;
    while (usedNumbers.has(nextNumber)) {
        nextNumber++;
    }

    return nextNumber;
}

/**
 * Find the next available number for a node type in a batch operation.
 * @param currentNodes All current nodes in the flow
 * @param type NodeType to find number for
 * @param namePrefix The prefix to match against (e.g., "Agent-Node" or "My Project")
 * @param allExistingNames Set of all existing names (including ones created in current batch)
 * @returns Next available number
 */
function getNextAvailableNumberForBatch(
    currentNodes: NodeModel[],
    type: NodeType,
    namePrefix: string,
    allExistingNames: Set<string>
): number {
    // Get all existing node names of this type from current nodes
    const existingNames = currentNodes.filter((n) => n.type === type).map((n) => n.node_name);

    // Extract numbers from existing names that match our prefix pattern
    const usedNumbers = new Set<number>();

    // Check both current nodes and names generated in this batch
    [...existingNames, ...Array.from(allExistingNames)].forEach((name) => {
        // Match pattern like "Agent-Node (#1)" or "My Project (#2)"
        const match = name.match(new RegExp(`^${namePrefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\(#(\\d+)\\)$`));
        if (match) {
            const number = parseInt(match[1], 10);
            usedNumbers.add(number);
        }
    });

    // Find the first available number starting from 1
    let nextNumber = 1;
    while (usedNumbers.has(nextNumber)) {
        nextNumber++;
    }

    return nextNumber;
}

/**
 * Generate display names for multiple nodes at once, ensuring each gets a unique count.
 * This is useful when creating multiple nodes simultaneously (like in copy/paste operations).
 * @param nodesToCreate Array of nodes to create with their types and data
 * @param currentNodes All current nodes in the flow (for counting)
 * @returns Array of display names in the same order as nodesToCreate
 */
export function generateMultipleNodeDisplayNames(
    nodesToCreate: Array<{ type: NodeType; data: unknown }>,
    currentNodes: NodeModel[]
): string[] {
    // Get all existing node names to avoid duplicates
    const existingNames = new Set(currentNodes.map((n) => n.node_name));

    // Count existing nodes by type
    const existingCounts = new Map<NodeType, number>();
    currentNodes.forEach((node) => {
        existingCounts.set(node.type, (existingCounts.get(node.type) || 0) + 1);
    });

    // Count nodes being created by type
    const creatingCounts = new Map<NodeType, number>();
    nodesToCreate.forEach((node) => {
        creatingCounts.set(node.type, (creatingCounts.get(node.type) || 0) + 1);
    });

    // Generate names for each node
    const displayNames: string[] = [];
    const generatedNames = new Set<string>(); // Track names generated in this batch

    nodesToCreate.forEach((node, index) => {
        const type = node.type;
        const data = node.data;

        // Get the name prefix for this node type
        const namePrefix =
            type === NodeType.PROJECT
                ? (data as { name?: string } | null)?.name || 'My Project'
                : NODE_TYPE_PREFIXES[type] || 'Node';

        // Get all existing node names of this type (including ones created in this batch)
        const allExistingNames = new Set([...existingNames, ...Array.from(generatedNames)]);

        // Find the next available number for this specific prefix
        const nextNumber = getNextAvailableNumberForBatch(currentNodes, type, namePrefix, allExistingNames);

        // Generate the display name
        let displayName: string;
        if (type === NodeType.PROJECT) {
            displayName = `${namePrefix} (#${nextNumber})`;
        } else {
            displayName = `${namePrefix} (#${nextNumber})`;
        }

        // Add to generated names set
        generatedNames.add(displayName);
        displayNames[index] = displayName;
    });

    return displayNames;
}
