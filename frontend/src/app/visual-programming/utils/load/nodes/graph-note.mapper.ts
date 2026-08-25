import { stableNodeId } from '../../stable-node-id';

import { GraphNote } from '../../../../pages/flows-page/components/flow-visual-programming/models/graph-note.model';
import { NodeType } from '../../../core/enums/node-type';
import { GraphNoteModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapGraphNoteToModel(nn: GraphNote): GraphNoteModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(nn.metadata, NodeType.NOTE);
    return {
        id: stableNodeId(NodeType.NOTE, nn.id),
        backendId: nn.id,
        type: NodeType.NOTE,
        node_name: nn.node_name,
        data: {
            content: nn.content,
            backgroundColor: nn.metadata?.['backgroundColor'] as string | undefined,
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}
