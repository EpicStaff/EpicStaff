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

export type WebhookAuthScheme = 'static_header' | 'hmac_sha256';

// `scheme`/`header_name`/`timestamp_header_name`/`tolerance_seconds`/`signing_secret` are
// server-generated (see `WebhookTriggerService.ensure_webhook_auth`) and only ever present
// once the backend has created this node's auth row — absent for a node not yet saved.
export interface WebhookNodeAuthModel {
    enabled: boolean;
    scheme?: WebhookAuthScheme;
    header_name?: string;
    timestamp_header_name?: string;
    tolerance_seconds?: number;
    signing_secret?: string | null;
}
