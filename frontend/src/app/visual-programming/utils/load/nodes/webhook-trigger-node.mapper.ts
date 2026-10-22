import { NodeType, toSecretIds, toSecretNames } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { GetWebhookTriggerNodeRequest } from '../../../core/models/webhook-trigger';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapWebhookTriggerNodeToModel(wn: GetWebhookTriggerNodeRequest): WebhookTriggerNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(wn.metadata, NodeType.WEBHOOK_TRIGGER);
    return {
        id: generateUuid(),
        backendId: wn.id,
        type: NodeType.WEBHOOK_TRIGGER,
        node_name: wn.node_name,
        nodeNumber: wn.node_number ?? undefined,
        data: {
            webhook_trigger: wn.webhook_trigger,
            python_code: {
                name: wn.node_name,
                libraries: wn.python_code.libraries,
                code: wn.python_code.code,
                entrypoint: wn.python_code.entrypoint,
                execution_timeout: wn.python_code.execution_timeout,
                secret_ids: toSecretIds(wn.python_code.secrets),
                secret_names: toSecretNames(wn.python_code.secrets),
            },
            test_payload: wn.test_payload ?? {},
            use_storage: wn.use_storage ?? false,
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
