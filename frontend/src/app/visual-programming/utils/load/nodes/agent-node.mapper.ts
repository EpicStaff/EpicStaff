import { generateUuid } from '@shared/utils';

import {
    AgentNode,
    AgentNodeTaskDto,
    AgentNodeTaskUi,
    AgentNodeTaskWrite,
} from '../../../../pages/flows-page/components/flow-visual-programming/models/agent-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { AgentNodeModel } from '../../../core/models/node.model';
import { stableNodeId } from '../../stable-node-id';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapAgentNodeToModel(an: AgentNode): AgentNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(an.metadata, NodeType.AGENT);

    const tasks: AgentNodeTaskUi[] = [...(an.tasks ?? [])]
        .sort((a, b) => a.order - b.order)
        .map((task) => {
            const wire = task as AgentNodeTaskDto & AgentNodeTaskWrite;
            const contextRefs =
                wire.context_tasks !== undefined
                    ? wire.context_tasks.map((id) => ({ id }))
                    : [
                          ...(wire.context_task_ids ?? []).map((id) => ({ id })),
                          ...(wire.context_task_temp_ids ?? []).map((tempId) => ({ tempId })),
                      ];

            return {
                id: task.id,
                tempId: wire.temp_id ?? generateUuid(),
                name: task.name,
                instructions: task.instructions,
                output_schema: task.output_schema ?? {},
                output_schema_invalid: false,
                contextRefs,
            };
        });

    return {
        id: stableNodeId(NodeType.AGENT, an.id),
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
