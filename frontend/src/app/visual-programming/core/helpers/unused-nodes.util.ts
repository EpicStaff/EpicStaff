import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { buildConnectionMaps, computeForwardContext } from './hover-context.util';
import { isTriggerNodeType } from './trigger-node-type.util';

/**
 * Returns the ids of nodes that no run can reach: no path leads to them from the Start node or a trigger.
 * Notes are never unused — they document the flow and take no connections.
 */
export function findUnusedNodeIds(nodes: NodeModel[], connections: ConnectionModel[]): Set<string> {
    const { outgoingMap } = buildConnectionMaps(connections);
    const reachable = new Set<string>();

    for (const node of nodes) {
        if (node.type === NodeType.START || isTriggerNodeType(node.type)) {
            computeForwardContext(node.id, outgoingMap).nodeIds.forEach((id) => reachable.add(id));
        }
    }

    return new Set(
        nodes.filter((node) => node.type !== NodeType.NOTE && !reachable.has(node.id)).map((node) => node.id)
    );
}
