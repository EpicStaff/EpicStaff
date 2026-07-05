import { WebhookTriggerModel } from '../../../../../visual-programming/core/models/webhook-trigger.model';

export interface TelegramTriggerField {
    field_name: string;
    field_type: string;
    description: string;
}

export interface TelegramTriggerFieldWithModel extends TelegramTriggerField {
    model: unknown;
}

export type TelegramFieldParent = 'message' | 'callback_query';

export interface DisplayedTelegramField extends TelegramTriggerFieldWithModel {
    id?: string;
    parent: string;
    variable_path: string;
}

export interface TelegramTriggerNodeField {
    id: number;
    parent: TelegramFieldParent;
    field_name: string;
    variable_path: string;
}

export interface GetTelegramTriggerNodeRequest {
    id: number;
    node_name: string;
    graph: number;
    telegram_bot_api_key: string;
    fields: TelegramTriggerNodeField[];
    metadata: Record<string, unknown>;
    webhook_trigger: WebhookTriggerModel | null;
}
