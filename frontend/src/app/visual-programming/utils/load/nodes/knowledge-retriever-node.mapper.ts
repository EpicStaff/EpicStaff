import { generateUuid } from '@shared/utils';

import { GetKnowledgeRetrieverNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/knowledge-retriever-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { KnowledgeRetrieverNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapKnowledgeRetrieverNodeToModel(kr: GetKnowledgeRetrieverNodeRequest): KnowledgeRetrieverNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(
        kr.metadata as Record<string, unknown> | undefined,
        NodeType.KNOWLEDGE_RETRIEVER
    );
    return {
        id: generateUuid(),
        backendId: kr.id,
        type: NodeType.KNOWLEDGE_RETRIEVER,
        node_name: kr.node_name,
        nodeNumber: ui.nodeNumber,
        data: kr,
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: kr.input_map ?? {},
        output_variable_path: kr.output_variable_path,
        size: ui.size,
    };
}
