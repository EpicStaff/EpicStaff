import { v4 as uuidv4 } from 'uuid';

import { GetCodeAgentNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/code-agent-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { CodeAgentNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapCodeAgentNodeToModel(ca: GetCodeAgentNodeRequest): CodeAgentNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(ca.metadata, NodeType.CODE_AGENT);
    return {
        id: uuidv4(),
        backendId: ca.id,
        type: NodeType.CODE_AGENT,
        node_name: ca.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            llm_config_id: ca.llm_config,
            agent_mode: ca.agent_mode ?? 'build',
            session_id: ca.session_id ?? '',
            system_prompt: ca.system_prompt ?? '',
            stream_handler_code: ca.stream_handler_code ?? '',
            libraries: ca.libraries ?? [],
            polling_interval_ms: ca.polling_interval_ms ?? 1000,
            silence_indicator_s: ca.silence_indicator_s ?? 3,
            indicator_repeat_s: ca.indicator_repeat_s ?? 5,
            chunk_timeout_s: ca.chunk_timeout_s ?? 30,
            inactivity_timeout_s: ca.inactivity_timeout_s ?? 120,
            max_wait_s: ca.max_wait_s ?? 300,
            output_schema: ca.output_schema ?? {},
            use_storage: ca.use_storage ?? false,
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: ca.input_map ?? {},
        output_variable_path: ca.output_variable_path,
        stream_config: ca.stream_config ?? {},
        size: ui.size,
    };
}
