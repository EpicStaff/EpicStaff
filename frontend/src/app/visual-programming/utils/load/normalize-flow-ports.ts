import { NodeType } from '../../core/enums/node-type';
import { generatePortsForDecisionTableNode, generatePortsForNode } from '../../core/helpers/helpers';
import { normalizeTableNodeSize } from '../../core/helpers/node-size.util';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';

/**
 * Generates ports for any node that has ports === null, and re-generates ports for
 * decision table nodes whose port count is out of sync with their condition groups.
 *
 * This normalization is applied both when loading a flow (so that savedFlowState
 * already reflects the port-filled state) and when FlowGraphComponent receives a
 * new flowState input (so the canvas has the correct ports).
 */
export function normalizeFlowPorts(flowState: FlowModel): FlowModel {
    let hasChanges = false;
    const nodes = flowState.nodes.map((node) => {
        let workingNode: NodeModel = node;

        if (workingNode.ports === null) {
            hasChanges = true;
            workingNode = {
                ...workingNode,
                ports: generatePortsForNode(workingNode.id, workingNode.type, workingNode.data),
            };
        }

        if (workingNode.type === NodeType.TABLE) {
            const tableData = (workingNode.data as { table?: { condition_groups?: unknown[] } })?.table;
            const conditionGroups = (tableData?.condition_groups ?? []) as Parameters<
                typeof generatePortsForDecisionTableNode
            >[1];
            const validGroups = conditionGroups.filter((g) => (g as { valid?: boolean })?.valid === true);
            // Expected: 1 input + N valid condition outputs + default + error
            const expectedPortCount = 1 + validGroups.length + 2;

            if (workingNode.ports!.length !== expectedPortCount) {
                hasChanges = true;
                workingNode = {
                    ...workingNode,
                    ports: generatePortsForDecisionTableNode(workingNode.id, conditionGroups),
                };
            }

            const normalizedSizeNode = normalizeTableNodeSize(workingNode);
            if (
                normalizedSizeNode.size?.height !== workingNode.size?.height ||
                normalizedSizeNode.size?.width !== workingNode.size?.width
            ) {
                hasChanges = true;
                workingNode = normalizedSizeNode;
            }
        }

        if (workingNode.type === NodeType.CLASSIFICATION_TABLE) {
            const normalizedSizeNode = normalizeTableNodeSize(workingNode);
            if (
                normalizedSizeNode.size?.height !== workingNode.size?.height ||
                normalizedSizeNode.size?.width !== workingNode.size?.width
            ) {
                hasChanges = true;
                workingNode = normalizedSizeNode;
            }
        }

        return workingNode;
    });

    return hasChanges ? { ...flowState, nodes } : flowState;
}
