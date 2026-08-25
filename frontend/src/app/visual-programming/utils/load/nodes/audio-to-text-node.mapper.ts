import { stableNodeId } from '../../stable-node-id';

import { GetAudioToTextNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { NodeType } from '../../../core/enums/node-type';
import { AudioToTextNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapAudioToTextNodeToModel(n: GetAudioToTextNodeRequest): AudioToTextNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(n.metadata, NodeType.AUDIO_TO_TEXT);
    return {
        id: stableNodeId(NodeType.AUDIO_TO_TEXT, n.id),
        backendId: n.id,
        type: NodeType.AUDIO_TO_TEXT,
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
