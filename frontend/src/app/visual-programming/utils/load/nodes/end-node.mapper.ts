import { stableNodeId } from '../../stable-node-id';

import { EndNode } from '../../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { EndNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapEndNodeToModel(en: EndNode): EndNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(en.metadata, NodeType.END);
    return {
        id: stableNodeId(NodeType.END, en.id),
        backendId: en.id,
        type: NodeType.END,
        node_name: en.node_name ?? '__end_node__',
        nodeNumber: ui.nodeNumber,
        data: { output_map: en.output_map ?? {} },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}
