import { WebhookTriggerWrite } from '@shared/models';

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

export interface CreateTelegramTriggerNodeField {
    parent: string;
    field_name: string;
    variable_path: string;
}

export interface CreateTelegramTriggerNodeRequest {
    node_name: string;
    graph: number;
    telegram_bot_api_key: string;
    webhook_trigger: WebhookTriggerWrite | null;
    fields: CreateTelegramTriggerNodeField[];
    metadata?: Record<string, unknown>;
}

export interface TelegramTriggerNodeField {
    id: number;
    parent: TelegramFieldParent;
    field_name: string;
    variable_path: string;
}

/** `GET telegram-trigger-nodes/{id}/webhook-info/` — what Telegram has registered for the node's bot key. */
export interface TelegramWebhookInfo {
    /** The URL Telegram currently delivers to for this bot key; null when nothing is registered. */
    registered_url: string | null;
    /** This node's own callback URL; null when the tunnel URL is unavailable or no trigger is set. */
    expected_url: string | null;
    /** false when nothing is registered or a different URL is; null only when `expected_url` is unknown. */
    is_match: boolean | null;
    pending_update_count: number | null;
    /** Telegram's last delivery error for this bot key. */
    last_error_message: string | null;
    /** ISO-8601. */
    last_error_date: string | null;
}

export interface GetTelegramTriggerNodeRequest {
    id: number;
    node_name: string;
    graph: number;
    telegram_bot_api_key_secret_id: number | null;
    fields: TelegramTriggerNodeField[];
    metadata: Record<string, unknown>;
    /** Nested object from the live API; a bare id when built from a version snapshot. */
    webhook_trigger: WebhookTriggerWrite | null;
}
