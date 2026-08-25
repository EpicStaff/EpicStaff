import { stableNodeId } from '../../stable-node-id';

import { StartNode } from '../../../../pages/flows-page/components/flow-visual-programming/models/start-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { StartNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapStartNodeToModel(sn: StartNode): StartNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(sn.metadata, NodeType.START);
    return {
        id: stableNodeId(NodeType.START, sn.id),
        backendId: sn.id,
        type: NodeType.START,
        node_name: '__start__',
        nodeNumber: ui.nodeNumber,
        data: { initialState: sn.variables ?? {} },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}
