export enum WebhookStatus {
    SUCCESS = 'success',
    FAIL = 'fail',
}

export interface GetTunnelResponse {
    status: WebhookStatus;
    tunnel_url?: string | null;
}
