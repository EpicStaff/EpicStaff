import { generateUuid } from '@shared/utils';

import { GetTelegramTriggerNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { NodeType } from '../../../core/enums/node-type';
import { TelegramTriggerNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapTelegramTriggerNodeToModel(tn: GetTelegramTriggerNodeRequest): TelegramTriggerNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(tn.metadata, NodeType.TELEGRAM_TRIGGER);
    return {
        id: generateUuid(),
        backendId: tn.id,
        type: NodeType.TELEGRAM_TRIGGER,
        node_name: tn.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            telegram_bot_api_key: tn.telegram_bot_api_key,
            webhook_trigger: tn.webhook_trigger,
            fields: tn.fields,
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {} as Record<string, unknown>,
        output_variable_path: null,
        size: ui.size,
    };
}
