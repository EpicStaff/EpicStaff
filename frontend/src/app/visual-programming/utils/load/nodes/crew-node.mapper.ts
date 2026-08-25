import { stableNodeId } from '../../stable-node-id';

import { CrewNode } from '../../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { ProjectNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapCrewNodeToModel(cn: CrewNode): ProjectNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(cn.metadata, NodeType.PROJECT);
    return {
        id: stableNodeId(NodeType.PROJECT, cn.id),
        backendId: cn.id,
        type: NodeType.PROJECT,
        node_name: cn.node_name,
        nodeNumber: ui.nodeNumber,
        data: cn.crew,
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: cn.input_map ?? {},
        output_variable_path: cn.output_variable_path,
        stream_config: cn.stream_config ?? {},
        size: ui.size,
    };
}
