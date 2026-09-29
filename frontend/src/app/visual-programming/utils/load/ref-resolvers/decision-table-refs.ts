import { GetDecisionTableNodeRequest } from '../../../core/models/decision-table-node.model';
import { DecisionTableNodeModel } from '../../../core/models/node.model';

/**
 * After all nodes are built and the backendId → UUID map exists,
 * fills in the UUID references inside each DT node's table data:
 *   - default_next_node
 *   - next_error_node
 *   - each condition group's next_node
 *
 * Mutates models in place — called once at load time before connections are built.
 */
export function resolveDecisionTableNodeRefs(
    decisionTableNodes: DecisionTableNodeModel[],
    backendDecisionTables: GetDecisionTableNodeRequest[],
    backendIdToUuid: Map<number, string>
): void {
    for (const dtNode of decisionTableNodes) {
        const backendDt = backendDecisionTables.find((d) => d.id === dtNode.backendId);
        if (!backendDt) continue;

        const table = dtNode.data.table;

        table.default_next_node =
            backendDt.default_next_node_id != null
                ? (backendIdToUuid.get(backendDt.default_next_node_id) ?? null)
                : null;

        table.next_error_node =
            backendDt.next_error_node_id != null ? (backendIdToUuid.get(backendDt.next_error_node_id) ?? null) : null;

        for (let j = 0; j < table.condition_groups.length; j++) {
            const group = table.condition_groups[j];
            const backendGroup = backendDt.condition_groups[j];
            if (backendGroup) {
                group.next_node =
                    backendGroup.next_node_id != null ? (backendIdToUuid.get(backendGroup.next_node_id) ?? null) : null;
            }
        }
    }
}
