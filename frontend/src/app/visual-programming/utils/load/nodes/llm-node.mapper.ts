import { v4 as uuidv4 } from 'uuid';

import { GetLLMNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { LLMNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapLLMNodeToModel(ln: GetLLMNodeRequest): LLMNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(ln.metadata, NodeType.LLM);
    const configDetail = ln.llm_config_detail ?? {
        id: ln.llm_config,
        custom_name: ln.node_name,
        model: 0,
        api_key: '',
        temperature: null,
        top_p: null,
        stop: null,
        max_tokens: null,
        presence_penalty: null,
        frequency_penalty: null,
        logit_bias: null,
        seed: null,
        timeout: null,
        is_visible: true,
        tags: [],
    };
    return {
        id: uuidv4(),
        backendId: ln.id,
        type: NodeType.LLM,
        node_name: ln.node_name,
        nodeNumber: ui.nodeNumber,
        data: configDetail,
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: ln.input_map ?? {},
        output_variable_path: ln.output_variable_path,
        size: ui.size,
    };
}
