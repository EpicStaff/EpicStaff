import { NodeModel } from '../models/node.model';

/** "Name #N" for lists where same-named nodes must be told apart. Display only — never stored. */
export function formatNodeLabel(node: Pick<NodeModel, 'node_name' | 'nodeNumber'>): string {
    return node.nodeNumber == null ? node.node_name : `${node.node_name} #${node.nodeNumber}`;
}
