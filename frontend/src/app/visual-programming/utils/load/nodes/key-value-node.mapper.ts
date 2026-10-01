import { NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { normalizeEntry } from '../../../core/helpers/key-value-node.helpers';
import { GetKeyValueNodeRequest } from '../../../core/models/key-value-node.model';
import { KeyValueNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapKeyValueNodeToModel(dto: GetKeyValueNodeRequest): KeyValueNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(
        dto.metadata as Record<string, unknown> | undefined,
        NodeType.KEY_VALUE
    );
    return {
        id: generateUuid(),
        backendId: dto.id,
        type: NodeType.KEY_VALUE,
        node_name: dto.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            key_value_table: dto.key_value_table,
            mode: dto.mode,
            entries: (dto.entries ?? []).map((entry) => normalizeEntry(entry, dto.mode)),
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: dto.input_map ?? {},
        // No key-value mode writes an output; read values go to each entry's own path.
        output_variable_path: null,
        size: ui.size,
    };
}
