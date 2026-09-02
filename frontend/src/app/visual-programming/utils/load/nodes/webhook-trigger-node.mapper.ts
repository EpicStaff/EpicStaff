import { GetWebhookTriggerNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import { NodeType } from '../../../core/enums/node-type';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { stableNodeId } from '../../stable-node-id';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapWebhookTriggerNodeToModel(wn: GetWebhookTriggerNodeRequest): WebhookTriggerNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(wn.metadata, NodeType.WEBHOOK_TRIGGER);
    return {
        id: stableNodeId(NodeType.WEBHOOK_TRIGGER, wn.id),
        backendId: wn.id,
        type: NodeType.WEBHOOK_TRIGGER,
        node_name: wn.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            webhook_trigger: wn.webhook_trigger,
            webhook_node_auth: wn.webhook_node_auth ?? null,
            python_code: {
                name: wn.node_name,
                libraries: wn.python_code.libraries,
                code: wn.python_code.code,
                entrypoint: wn.python_code.entrypoint,
                ...(wn.python_code.secret_ids !== undefined ? { secret_ids: wn.python_code.secret_ids } : {}),
            },
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: wn.input_map ?? {},
        output_variable_path: wn.output_variable_path,
        size: ui.size,
    };
}
