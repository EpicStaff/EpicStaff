import { stableNodeId } from '../../stable-node-id';

import { GetFileExtractorNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { NodeType } from '../../../core/enums/node-type';
import { FileExtractorNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapFileExtractorNodeToModel(n: GetFileExtractorNodeRequest): FileExtractorNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(n.metadata, NodeType.FILE_EXTRACTOR);
    return {
        id: stableNodeId(NodeType.FILE_EXTRACTOR, n.id),
        backendId: n.id,
        type: NodeType.FILE_EXTRACTOR,
        node_name: n.node_name,
        nodeNumber: ui.nodeNumber,
        data: undefined,
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: n.input_map ?? {},
        output_variable_path: n.output_variable_path,
        size: ui.size,
    };
}
