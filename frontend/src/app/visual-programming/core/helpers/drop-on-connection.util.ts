import { NodeType } from '@shared/models';

import { createFlowConnection } from '../../utils/connection.factory';
import { polylineIntersectsRect, Rect } from '../geometry/connection-hit-test';
import { getPortPosition } from '../geometry/port-position';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { ViewPort } from '../models/port.model';

export interface DropOnConnectionResult {
    /** The connection to remove */
    connectionToRemove: ConnectionModel;
    /** Two new connections: [source -> droppedNode, droppedNode -> target] */
    newConnections: [ConnectionModel, ConnectionModel];
}

/** Find the first connection whose path intersects the node's bounding box. Returns null if none. */
export function findConnectionUnderNode(
    node: NodeModel,
    connections: ConnectionModel[],
    nodesById: Map<string, NodeModel>
): ConnectionModel | null {
    const nodeRect: Rect = {
        x: node.position.x,
        y: node.position.y,
        width: node.size.width,
        height: node.size.height,
    };

    for (const connection of connections) {
        if (connection.sourceNodeId === node.id || connection.targetNodeId === node.id) {
            continue;
        }

        const sourceNode = nodesById.get(connection.sourceNodeId);
        const targetNode = nodesById.get(connection.targetNodeId);
        if (!sourceNode || !targetNode) continue;

        const sourcePort = sourceNode.ports?.find((port) => port.id === connection.sourcePortId);
        const targetPort = targetNode.ports?.find((port) => port.id === connection.targetPortId);

        const sourcePosition = getPortPosition(sourceNode, sourcePort);
        const targetPosition = getPortPosition(targetNode, targetPort);

        const pathPoints = [sourcePosition, ...(connection.waypoints ?? []), targetPosition];

        if (polylineIntersectsRect(pathPoints, nodeRect)) {
            return connection;
        }
    }

    return null;
}

function resolveInputPort(node: NodeModel): ViewPort | undefined {
    return node.ports?.find((port) => port.port_type === 'input');
}

function resolveOutputPort(node: NodeModel): ViewPort | undefined {
    if (node.type === NodeType.TABLE || node.type === NodeType.CLASSIFICATION_TABLE) {
        return node.ports?.find((port) => port.role === 'decision-default');
    }
    return node.ports?.find((port) => port.port_type === 'output');
}

/** Build the two replacement connections when inserting a node into a connection. Returns null if the node has no suitable ports. */
export function buildInsertionConnections(node: NodeModel, connection: ConnectionModel): DropOnConnectionResult | null {
    const inputPort = resolveInputPort(node);
    const outputPort = resolveOutputPort(node);

    if (!inputPort || !outputPort) return null;

    const sourceToNode = createFlowConnection(connection.sourceNodeId, node.id, connection.sourcePortId, inputPort.id);

    const nodeToTarget = createFlowConnection(node.id, connection.targetNodeId, outputPort.id, connection.targetPortId);

    return {
        connectionToRemove: connection,
        newConnections: [sourceToNode, nodeToTarget],
    };
}
