/** A node as far as its label goes: the name, and the display-only number when the node has one. */
export interface NodeLabelSource {
    node_name: string;
    nodeNumber?: number | null;
}

/** "Name #N" for lists where same-named nodes must be told apart. Display only — never stored. */
export function formatNodeLabel(node: NodeLabelSource): string {
    return node.nodeNumber == null ? node.node_name : `${node.node_name} #${node.nodeNumber}`;
}
