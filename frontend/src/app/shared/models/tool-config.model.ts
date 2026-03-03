export interface ToolConfig {
  id: number; // Represents the unique identifier for the tool configuration
  name: string;
  configuration: Record<string, any>; // Allows any number of key-value pairs where both key and value are strings
  tool: number; // Represents the tool ID
  is_completed: boolean;
  toolName?: string;
  toolDescription?: string;
}
export interface ToolConfigDto {
  id: number; // Represents the unique identifier for the tool configuration
  name: string;
  configuration: Record<string, any>; // Allows any number of key-value pairs where both key and value are strings
  tool: number; // Represents the tool ID
  is_completed: boolean;
}

export interface GetToolConfigDto {
  id: number; // Represents the unique identifier for the tool configuration
  name: string;
  configuration: Record<string, any>; // Allows any number of key-value pairs where both key and value are strings
  tool: number; // Represents the tool ID
  is_completed: boolean;
}
export interface GetToolConfigRequest {
  id: number; // Represents the unique identifier for the tool configuration
  name: string;
  configuration: Record<string, any>; // Allows any number of key-value pairs where both key and value are strings
  tool: number; // Represents the tool ID
  is_completed: boolean;
}

export interface CreateToolConfigRequest {
  name: string;
  configuration: Record<string, any>;
  tool: number;
}
