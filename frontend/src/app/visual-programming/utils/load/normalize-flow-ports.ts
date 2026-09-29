import { NodeType } from '@shared/models';

import { generatePortsForDecisionTableNode, generatePortsForNode } from '../../core/helpers/helpers';
import { FlowModel } from '../../core/models/flow.model';

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
        if (node.ports === null) {
            hasChanges = true;
            return { ...node, ports: generatePortsForNode(node.id, node.type, node.data) };
        }

        if (node.type === NodeType.TABLE) {
            const tableData = (node.data as { table?: { condition_groups?: unknown[] } })?.table;
            const conditionGroups = (tableData?.condition_groups ?? []) as Parameters<
                typeof generatePortsForDecisionTableNode
            >[1];
            // Same predicate as generatePortsForDecisionTableNode (`valid !== false`); a stricter
            // one here made every group with `valid` unset look out of sync, so the node was
            // regenerated on every pass and normalizeFlowPorts never returned its input unchanged.
            const validGroups = conditionGroups.filter((g) => (g as { valid?: boolean })?.valid !== false);
            // Expected: 1 input + N valid condition outputs + default + error
            const expectedPortCount = 1 + validGroups.length + 2;

            if (node.ports.length !== expectedPortCount) {
                hasChanges = true;
                return {
                    ...node,
                    ports: generatePortsForDecisionTableNode(node.id, conditionGroups),
                };
            }
        }

        return node;
    });

    return hasChanges ? { ...flowState, nodes } : flowState;
}
