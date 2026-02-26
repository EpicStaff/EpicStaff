export interface ToolConfig {
  id: number;
  name: string;
  configuration: Record<string, any>;
  tool: number;
  is_completed: boolean;
  toolName?: string;
  toolDescription?: string;
}

export interface GetToolConfigRequest {
  id: number;
  name: string;
  configuration: Record<string, any>;
  tool: number;
  is_completed: boolean;
}

export interface CreateToolConfigRequest {
  name: string;
  configuration: Record<string, any>;
  tool: number;
}
