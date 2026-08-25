import { stableNodeId } from '../../stable-node-id';

import { GetDecisionTableNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { DecisionTableNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapDecisionTableNodeToModel(dn: GetDecisionTableNodeRequest): DecisionTableNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(dn.metadata, NodeType.TABLE);
    return {
        id: stableNodeId(NodeType.TABLE, dn.id),
        backendId: dn.id,
        type: NodeType.TABLE,
        node_name: dn.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            name: dn.node_name,
            table: {
                // default_next_node / next_error_node / group next_node are resolved
                // after all nodes are built — see ref-resolvers/decision-table-refs.ts
                default_next_node: null,
                next_error_node: null,
                condition_groups: dn.condition_groups.map((g) => ({
                    group_name: g.group_name,
                    group_type: g.group_type as 'simple' | 'complex',
                    expression: g.expression,
                    conditions: g.conditions.map((c) => ({
                        condition_name: c.condition_name,
                        condition: c.condition,
                    })),
                    manipulation: g.manipulation,
                    next_node: null,
                    valid: true,
                    order: g.order,
                })),
            },
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {} as Record<string, unknown>,
        output_variable_path: null,
        size: ui.size,
    };
}
