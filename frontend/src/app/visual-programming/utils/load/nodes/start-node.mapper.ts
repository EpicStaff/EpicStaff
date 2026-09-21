import { NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { StartNodeModel } from '../../../core/models/node.model';
import { StartNode } from '../../../core/models/start-node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapStartNodeToModel(sn: StartNode): StartNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(sn.metadata, NodeType.START);
    return {
        id: generateUuid(),
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
