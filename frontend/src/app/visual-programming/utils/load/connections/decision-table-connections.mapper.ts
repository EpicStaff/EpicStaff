import { GetDecisionTableNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { ConnectionModel } from '../../../core/models/connection.model';
import { DecisionTableNodeModel, NodeModel } from '../../../core/models/node.model';
import { CustomPortId } from '../../../core/models/port.model';
import { createFlowConnection } from '../../connection.factory';
import { getInputPortRole } from '../../node-port-roles';

/**
 * Maps DT output ports (condition groups, default, error) to canvas connections.
 * EDGE node targets are skipped — those wires come from mapConditionalEdgesToConnections.
 */
export function mapDecisionTableToConnections(
    decisionTableNodes: DecisionTableNodeModel[],
    backendIdToUuid: Map<number, string>,
    nodeByBackendId: Map<number, NodeModel>,
    backendDecisionTables: GetDecisionTableNodeRequest[]
): ConnectionModel[] {
    const connections: ConnectionModel[] = [];

    for (let i = 0; i < decisionTableNodes.length; i++) {
        const dtNode = decisionTableNodes[i];
        const backendDt = backendDecisionTables[i];
        if (!backendDt) {
            console.warn(`[DT-connections] No backend DT at index ${i} for dtNode ${dtNode.id}`);
            continue;
        }

        for (const group of backendDt.condition_groups) {
            if (group.next_node_id == null) continue;
            const targetUuid = backendIdToUuid.get(group.next_node_id);
            if (!targetUuid) {
                console.warn(
                    `[DT-connections] Group "${group.group_name}": next_node_id=${group.next_node_id} not found`
                );
                continue;
            }
            const targetNode = nodeByBackendId.get(group.next_node_id);
            if (targetNode && targetNode.type !== NodeType.EDGE) {
                const normalizedName = group.group_name.toLowerCase().replace(/\s+/g, '-');
                connections.push(
                    createFlowConnection(
                        dtNode.id,
                        targetUuid,
                        `${dtNode.id}_decision-out-${normalizedName}` as CustomPortId,
                        `${targetUuid}_${getInputPortRole(targetNode.type)}` as CustomPortId
                    )
                );
            }
        }

        if (backendDt.default_next_node_id != null) {
            const targetUuid = backendIdToUuid.get(backendDt.default_next_node_id);
            if (targetUuid) {
                const targetNode = nodeByBackendId.get(backendDt.default_next_node_id);
                if (targetNode && targetNode.type !== NodeType.EDGE) {
                    connections.push(
                        createFlowConnection(
                            dtNode.id,
                            targetUuid,
                            `${dtNode.id}_decision-default` as CustomPortId,
                            `${targetUuid}_${getInputPortRole(targetNode.type)}` as CustomPortId
                        )
                    );
                }
            } else {
                console.warn(`[DT-connections] default_next_node_id=${backendDt.default_next_node_id} not found`);
            }
        }

        if (backendDt.next_error_node_id != null) {
            const targetUuid = backendIdToUuid.get(backendDt.next_error_node_id);
            if (targetUuid) {
                const targetNode = nodeByBackendId.get(backendDt.next_error_node_id);
                if (targetNode && targetNode.type !== NodeType.EDGE) {
                    connections.push(
                        createFlowConnection(
                            dtNode.id,
                            targetUuid,
                            `${dtNode.id}_decision-error` as CustomPortId,
                            `${targetUuid}_${getInputPortRole(targetNode.type)}` as CustomPortId
                        )
                    );
                }
            } else {
                console.warn(`[DT-connections] next_error_node_id=${backendDt.next_error_node_id} not found`);
            }
        }
    }

    return connections;
}
