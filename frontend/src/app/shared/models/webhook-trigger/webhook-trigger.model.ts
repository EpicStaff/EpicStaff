import { LastEditFields } from '../authorship.model';

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

// Also the nested write payload, so the read-only last-edit fields are optional.
export interface WebhookTriggerModel extends Partial<LastEditFields> {
    id?: number;
    path: string;
    provider_type: WebhookProviderType | null;
    ngrok_config: NgrokConfigInline | null;
    localhost_config: LocalhostConfigInline | null;
    live_url?: string | null;
    auth_kind?: WebhookTriggerAuthKind;
    auth_secret_id?: number | null;
    auth?: WebhookTriggerAuth | null;
}

// Write payload accepted by the node serializers: int PK or nested object.
export type WebhookTriggerWrite = number | WebhookTriggerModel;
