export interface GetMcpToolRequest {
  id: number;
  name: string;
  transport: string;
  tool_name: string;
  timeout?: number;
  auth?: string | null;
  init_timeout?: number;
}

export interface CreateMcpToolRequest {
  name: string;
  transport: string;
  tool_name: string;
  timeout?: number;
  auth?: string | null;
  init_timeout?: number;
}

export interface UpdateMcpToolRequest {
  name?: string;
  transport?: string;
  tool_name?: string;
  timeout?: number;
  auth?: string | null;
  init_timeout?: number;
}

