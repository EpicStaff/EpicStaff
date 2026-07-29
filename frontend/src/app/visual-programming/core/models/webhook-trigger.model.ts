export type WebhookProviderType = 'ngrok' | 'localhost';

export interface NgrokConfigInline {
    name: string;
    auth_token: string;
    domain: string | null;
    region: 'us' | 'eu' | 'ap';
}

export interface LocalhostConfigInline {
    name: string;
    domain?: string | null;
}

export interface WebhookTriggerModel {
    id?: number;
    path: string;
    provider_type: WebhookProviderType | null;
    ngrok_config: NgrokConfigInline | null;
    localhost_config: LocalhostConfigInline | null;
    live_url?: string | null;
}

// Write payload accepted by the node serializers: int PK or nested object.
export type WebhookTriggerWrite = number | WebhookTriggerModel;
