import { IPoint } from '@foblex/2d';

import { Edge } from '../../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { NodeType } from '../../../core/enums/node-type';
import { ConnectionModel } from '../../../core/models/connection.model';
import { NodeModel } from '../../../core/models/node.model';
import { CustomPortId } from '../../../core/models/port.model';
import { createFlowConnection } from '../../connection.factory';
import { getInputPortRole, getOutputPortRole } from '../../node-port-roles';

function extractPersistedWaypoints(metadata: Record<string, unknown>): IPoint[] | undefined {
    const raw = metadata?.['waypoints'];
    if (!Array.isArray(raw) || raw.length === 0) return undefined;
    return raw as IPoint[];
}

/**
 * Maps plain edges (edge_list) to canvas connections.
 * Skips edges where the source is a TABLE or EDGE node — those are
 * handled by their own mappers.
 */
export function mapEdgesToConnections(
    edges: Edge[],
    backendIdToUuid: Map<number, string>,
    nodeByBackendId: Map<number, NodeModel>
): ConnectionModel[] {
    const connections: ConnectionModel[] = [];

    for (const edge of edges) {
        const sourceUuid = backendIdToUuid.get(edge.start_node_id);
        const targetUuid = backendIdToUuid.get(edge.end_node_id);
        if (!sourceUuid || !targetUuid) {
            console.warn('[load:edges] skip edge: missing node uuid mapping', {
                edgeId: edge.id,
                startNodeId: edge.start_node_id,
                endNodeId: edge.end_node_id,
                hasSourceUuid: !!sourceUuid,
                hasTargetUuid: !!targetUuid,
            });
            continue;
        }

        const sourceNode = nodeByBackendId.get(edge.start_node_id);
        const targetNode = nodeByBackendId.get(edge.end_node_id);
        if (!sourceNode || !targetNode) {
            console.warn('[load:edges] skip edge: missing node model by backend id', {
                edgeId: edge.id,
                startNodeId: edge.start_node_id,
                endNodeId: edge.end_node_id,
                hasSourceNode: !!sourceNode,
                hasTargetNode: !!targetNode,
            });
            continue;
        }

        if (sourceNode.type === NodeType.TABLE || sourceNode.type === NodeType.EDGE) {
            continue;
        }
        if (targetNode.type === NodeType.EDGE) {
            continue;
        }

        const restoredWaypoints = extractPersistedWaypoints(edge.metadata ?? {});

        connections.push({
            ...createFlowConnection(
                sourceUuid,
                targetUuid,
                `${sourceUuid}_${getOutputPortRole(sourceNode.type)}` as CustomPortId,
                `${targetUuid}_${getInputPortRole(targetNode.type)}` as CustomPortId
            ),
            data: edge,
            ...(restoredWaypoints ? { waypoints: restoredWaypoints, userAdjustedWaypoints: true } : {}),
        });
    }

    return connections;
}
