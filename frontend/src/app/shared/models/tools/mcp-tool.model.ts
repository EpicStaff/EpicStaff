export interface GetMcpToolRequest {
    id: number;
    name: string;
    labels: number[];
    transport: string;
    tool_name: string;
    timeout?: number;
    auth_secret_id?: number | null;
    init_timeout?: number;
    org: number;
    created_by: number;
    is_favorite: boolean;
    created_at: string;
    updated_at: string;
}

export interface CreateMcpToolRequest {
    name: string;
    labels?: number[];
    transport: string;
    tool_name: string;
    timeout?: number;
    auth_secret_id?: number | null;
    init_timeout?: number;
}

export interface UpdateMcpToolRequest {
    name?: string;
    labels?: number[];
    transport?: string;
    tool_name?: string;
    timeout?: number;
    auth_secret_id?: number | null;
    init_timeout?: number;
}
