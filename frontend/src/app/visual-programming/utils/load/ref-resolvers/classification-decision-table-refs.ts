import { GetClassificationDecisionTableNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/classification-decision-table-node.model';
import { ClassificationDecisionTableNodeModel } from '../../../core/models/node.model';

/**
 * After all nodes are built and the backendId → UUID map exists, fills in
 * UUID references inside each CDT node's table data:
 *   - default_next_node (stored as backend integer ID → resolve to UUID)
 *   - next_error_node (stored as backend integer ID → resolve to UUID)
 *   - each condition group's next_node (stored as backend integer ID → resolve to UUID)
 *
 * Mutates models in place — called once at load time before connections are built.
 */
export function resolveClassificationDecisionTableNodeRefs(
    cdtNodes: ClassificationDecisionTableNodeModel[],
    backendCdtNodes: GetClassificationDecisionTableNodeRequest[],
    backendIdToUuid: Map<number, string>
): void {
    for (const cdtNode of cdtNodes) {
        const backendCdt = backendCdtNodes.find((d) => d.id === cdtNode.backendId);
        if (!backendCdt) continue;

        const table = cdtNode.data.table;

        // default_next_node and next_error_node come back as backend integer IDs — resolve to FE UUID
        table.default_next_node =
            backendCdt.default_next_node_id != null
                ? (backendIdToUuid.get(backendCdt.default_next_node_id) ?? null)
                : null;

        table.next_error_node =
            backendCdt.next_error_node_id != null ? (backendIdToUuid.get(backendCdt.next_error_node_id) ?? null) : null;

        // Condition groups carry next_node_id (backend integer) — resolve to FE UUID
        for (let j = 0; j < table.condition_groups.length; j++) {
            const group = table.condition_groups[j];
            const backendGroup = backendCdt.condition_groups[j];
            if (backendGroup?.next_node_id != null) {
                group.next_node = backendIdToUuid.get(backendGroup.next_node_id) ?? null;
            } else {
                group.next_node = null;
            }
        }
    }
}
