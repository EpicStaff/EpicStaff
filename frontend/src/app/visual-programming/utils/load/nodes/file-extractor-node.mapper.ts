import { NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { GetFileExtractorNodeRequest } from '../../../core/models/file-extractor.model';
import { FileExtractorNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapFileExtractorNodeToModel(n: GetFileExtractorNodeRequest): FileExtractorNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(n.metadata, NodeType.FILE_EXTRACTOR);
    return {
        id: generateUuid(),
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
