import { v4 as uuidv4 } from 'uuid';

import { TaskNode } from '../../../../pages/flows-page/components/flow-visual-programming/models/task-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { TaskNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapTaskNodeToModel(tn: TaskNode): TaskNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(tn.metadata, NodeType.TASK);
    return {
        id: uuidv4(),
        backendId: tn.id,
        type: NodeType.TASK,
        node_name: tn.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            name: tn.node_name,
            instructions: tn.instructions,
            output_schema: tn.output_schema ?? {},
            remember_output: tn.remember_output ?? false,
            agent_definition: tn.agent_definition ?? null,
            content_hash: tn.content_hash,
            surface_list: tn.surface_list ?? [],
            inline_surface: tn.inline_surface ?? null,
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: tn.input_map ?? {},
        output_variable_path: tn.output_variable_path,
        size: ui.size,
    };
}
