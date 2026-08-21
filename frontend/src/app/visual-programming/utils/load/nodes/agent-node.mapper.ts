import { generateUuid } from '@shared/utils';

import {
    AgentNode,
    AgentNodeTaskUi,
} from '../../../../pages/flows-page/components/flow-visual-programming/models/agent-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { AgentNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapAgentNodeToModel(an: AgentNode): AgentNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(an.metadata, NodeType.AGENT);

    const tasks: AgentNodeTaskUi[] = [...(an.tasks ?? [])]
        .sort((a, b) => a.order - b.order)
        .map((task) => ({
            id: task.id,
            // Fresh client-side id for stable row tracking (drag-reorder, table trackBy).
            // Persistence still keys off `id`; `tempId` is never sent for existing tasks.
            tempId: generateUuid(),
            name: task.name,
            instructions: task.instructions,
            output_schema: task.output_schema ?? {},
            output_schema_invalid: false,
            contextRefs: (task.context_tasks ?? []).map((id) => ({ id })),
        }));

    return {
        id: generateUuid(),
        backendId: an.id,
        type: NodeType.AGENT,
        node_name: an.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            name: an.node_name,
            agent_definition: an.agent_definition ?? null,
            surface_list: an.surface_list ?? [],
            inline_surface: an.inline_surface ?? null,
            tasks,
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: an.input_map ?? {},
        output_variable_path: an.output_variable_path,
        size: ui.size,
    };
}
