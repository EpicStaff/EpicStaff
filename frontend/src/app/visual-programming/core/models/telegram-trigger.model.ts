import { AuthorshipFields } from '@shared/models';

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
    /** Bulk save accepts only the id of an existing trigger; triggers are created through `/webhook-triggers/`. */
    webhook_trigger: number | null;
    fields: CreateTelegramTriggerNodeField[];
    metadata?: Record<string, unknown>;
}

export interface TelegramTriggerNodeField {
    id: number;
    parent: TelegramFieldParent;
    field_name: string;
    variable_path: string;
}

export interface GetTelegramTriggerNodeRequest extends AuthorshipFields {
    id: number;
    created_at: string;
    node_name: string;
    graph: number;
    telegram_bot_api_key_secret_id: number | null;
    fields: TelegramTriggerNodeField[];
    metadata: Record<string, unknown>;
    /** Id of the referenced webhook trigger — the graph API and the version snapshot both send a bare id. */
    webhook_trigger: number | null;
}
