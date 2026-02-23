export interface LLM_Model {
  id: number;
  name: string;
  description: string | null;
  base_url: string | null;
  deployment_id: string | null;
  api_version: string | null;
  is_visible: boolean;
  is_custom: boolean;
  predefined: boolean; // Indicates if model should be shown by default (favorite)

  llm_provider: number;
}

export interface GetLlmModelRequest {
  id: number;
  name: string;
  description: string | null;
  base_url: string | null;
  deployment_id: string | null;
  api_version: string | null;
  is_visible: boolean;
  is_custom: boolean;
  predefined: boolean;

  llm_provider: number;
}

export interface CreateLlmModelRequest {
  name: string;
  description?: string | null;
  base_url?: string | null;
  deployment_id?: string | null;
  api_version?: string | null;
  is_visible: boolean;
  is_custom: boolean;
  predefined?: boolean;
  llm_provider: number;
}
