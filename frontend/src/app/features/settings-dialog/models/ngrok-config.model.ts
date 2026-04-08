export interface CreateNgrokConfigRequest {
    name: string;
    auth_token: string;
    domain?: string;
    region?: string;
}

export interface GetNgrokConfigResponse {
    id: number;
    name: string;
    auth_token: string;
    domain: string;
    region: string;
    webhook_full_url: string | null;
}
