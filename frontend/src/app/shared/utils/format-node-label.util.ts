/** A node as far as its label goes: the name, and the display-only number when the node has one. */
export interface NodeLabelSource {
    node_name: string;
    nodeNumber?: number | null;
}

/** "Name #N" for lists where same-named nodes must be told apart. Display only — never stored. */
export function formatNodeLabel(node: NodeLabelSource): string {
    return node.nodeNumber == null ? node.node_name : `${node.node_name} #${node.nodeNumber}`;
}

const RUNTIME_NODE_ID_SUFFIX = / #\d+$/;

/**
 * The label of a runtime node name: "Fetch #3 #1742" becomes "Fetch #3".
 * Inverse of the backend `graph_utils.runtime_node_name`, which appends exactly one " #<node id>"
 * to the label; a name without that suffix comes back unchanged.
 * DISPLAY ONLY: never use it for grouping, filtering or lookups — two different nodes can share
 * a label, only the full name is unique.
 */
export function runtimeNodeNameToLabel(name: string): string {
    return name.replace(RUNTIME_NODE_ID_SUFFIX, '');
}
