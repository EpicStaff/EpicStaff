import { AuthorshipFields } from '../authorship.model';

export type WebhookProviderType = 'ngrok' | 'localhost';

export interface NgrokConfigInline {
    name: string;
    auth_token_secret_id: number | null;
    domain: string | null;
    region: 'us' | 'eu' | 'ap';
}

export interface LocalhostConfigInline {
    name: string;
    domain?: string | null;
}

export type WebhookTriggerAuthKind = 'webhook' | 'telegram' | 'twilio';

export interface WebhookTriggerAuth {
    kind: WebhookTriggerAuthKind;
    secret_tail: string | null;
}

// Also built client-side as the form value of webhook-trigger-field, so the read-only
// author, creation time and last-edit fields are optional.
export interface WebhookTriggerModel extends Partial<AuthorshipFields> {
    id?: number;
    path: string;
    provider_type: WebhookProviderType | null;
    ngrok_config: NgrokConfigInline | null;
    localhost_config: LocalhostConfigInline | null;
    live_url?: string | null;
    auth_kind?: WebhookTriggerAuthKind;
    auth_secret_id?: number | null;
    auth?: WebhookTriggerAuth | null;
    /** Read-only ISO 8601 creation time; null for triggers created before it was recorded. */
    created_at?: string | null;
}

// Body of `POST`/`PATCH /webhook-triggers/`: only the writable fields. The read-only ones
// (`id`, `live_url`, `auth`, the author, the creation time, the last edit) are never sent back.
export type WebhookTriggerPayload = Pick<
    WebhookTriggerModel,
    'path' | 'provider_type' | 'ngrok_config' | 'localhost_config' | 'auth_kind' | 'auth_secret_id'
>;

// Form value of webhook-trigger-field: an existing trigger's PK or a trigger being edited.
// Node serializers accept only the PK; new triggers are created via WebhookTriggerService.
export type WebhookTriggerWrite = number | WebhookTriggerModel;
