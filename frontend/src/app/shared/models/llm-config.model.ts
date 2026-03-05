export interface GetLlmConfigRequest {
  id: number;
  temperature: number;
  num_ctx: number;
  is_visible: boolean;
  model: number;
  api_key: string;
  custom_name: string;
}

export interface CreateLLMConfigRequest {
  temperature?: number;
  num_ctx?: number;
  is_visible?: boolean;
  model: number;
  api_key: string;
  custom_name: string;
}

export interface UpdateLLMConfigRequest {
  id: number;
  temperature: number;
  num_ctx: number;
  api_key: string;
  is_visible: boolean;
  model: number;
  custom_name: string;
}
