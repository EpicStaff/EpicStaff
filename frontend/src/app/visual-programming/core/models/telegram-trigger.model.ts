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
    test_payload: Record<string, unknown>;
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
    /** Why this node's webhook cannot be registered; null when registration can run. */
    registration_blocker: TelegramRegistrationBlocker | null;
}

/**
 * Codes the webhook-info and register-webhook endpoints report. The backend's `no_bot_key` blocker
 * never appears here: a missing bot key is answered with a 400 `telegram_bot_key_not_configured`.
 */
export type TelegramRegistrationBlockerCode =
    | 'no_webhook_trigger'
    | 'no_tunnel_provider'
    | 'localhost_provider'
    | 'auth_kind_conflict'
    | 'no_telegram_secret'
    | 'invalid_telegram_secret'
    | 'unresolvable_telegram_secret';

export interface TelegramRegistrationBlocker {
    /** A newer backend may send a code this UI does not know yet, so it is not narrowed to the union. */
    code: TelegramRegistrationBlockerCode | (string & Record<never, never>);
    /** Human-readable, never contains a secret. Shown only for codes the UI has no copy for. */
    message: string;
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
    /** Payload used by "Run with test payload": `{[parent]: {[field_name]: value}}`, `{}` when unset. */
    test_payload: Record<string, unknown>;
}
