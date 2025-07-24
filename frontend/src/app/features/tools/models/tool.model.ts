export interface Tool {
  id: number;
  name: string;
  name_alias: string;
  description: string;
  enabled: boolean;
  tool_fields: ToolField[];
}

export type ToolFieldDataType =
  | 'llm_config'
  | 'embedding_config'
  | 'string'
  | 'boolean'
  | 'integer'
  | 'any';

export interface ToolField {
  name: string;
  description: string;
  data_type: ToolFieldDataType;
  required: boolean;
}

export interface GetToolRequest {
  id: number;
  name: string;
  name_alias: string;
  description: string;
  enabled: boolean;
  tool_fields: ToolField[];
}
