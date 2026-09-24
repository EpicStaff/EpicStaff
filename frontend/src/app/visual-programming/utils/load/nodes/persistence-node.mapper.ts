import { NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { PersistenceNodeModel } from '../../../core/models/node.model';
import { GetPersistenceNodeRequest } from '../../../core/models/persistence-node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapPersistenceNodeToModel(dto: GetPersistenceNodeRequest): PersistenceNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(
        dto.metadata as Record<string, unknown> | undefined,
        NodeType.PERSISTENCE
    );
    return {
        id: generateUuid(),
        backendId: dto.id,
        type: NodeType.PERSISTENCE,
        node_name: dto.node_name,
        nodeNumber: ui.nodeNumber,
        data: { persistence_table: dto.persistence_table, mode: dto.mode, entries: dto.entries ?? [] },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: dto.input_map ?? {},
        output_variable_path: dto.output_variable_path,
        size: ui.size,
    };
}
