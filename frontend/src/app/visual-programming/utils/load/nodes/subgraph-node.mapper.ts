import { stableNodeId } from '../../stable-node-id';

import { SubGraphNode } from '../../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { SubGraphNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapSubGraphNodeToModel(sn: SubGraphNode): SubGraphNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(sn.metadata, NodeType.SUBGRAPH);
    const subgraphDetail = sn.subgraph_detail ?? {
        id: sn.subgraph,
        uuid: '',
        name: sn.node_name,
        description: '',
        tags: [],
    };
    return {
        id: stableNodeId(NodeType.SUBGRAPH, sn.id),
        backendId: sn.id,
        type: NodeType.SUBGRAPH,
        node_name: sn.node_name,
        nodeNumber: ui.nodeNumber,
        data: subgraphDetail,
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: sn.input_map ?? {},
        output_variable_path: sn.output_variable_path,
        size: ui.size,
        isBlocked: false,
    };
}
