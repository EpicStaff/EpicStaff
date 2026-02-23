export interface GetLlmConfigRequest {
  id: number;
    custom_name: string;
  model: number;
  api_key: string;
    temperature: number | null;
    top_p: number | null;
    stop: string[] | null;
    max_tokens: number | null;
    presence_penalty: number | null;
    frequency_penalty: number | null;
    logit_bias: Record<string, number> | null;
    response_format: Record<string, unknown> | null;
    seed: number | null;
    timeout: number | null;
    is_visible: boolean;
    headers?: Record<string, string>;
    extra_headers?: Record<string, string>;
}

export interface CreateLLMConfigRequest {
    custom_name: string;
  model: number;
  api_key: string;
    temperature?: number | null;
    top_p?: number | null;
    stop?: string[] | null;
    max_tokens?: number | null;
    presence_penalty?: number | null;
    frequency_penalty?: number | null;
    logit_bias?: Record<string, number> | null;
    response_format?: Record<string, unknown> | null;
    seed?: number | null;
    timeout?: number | null;
    is_visible?: boolean;
    headers?: Record<string, string>;
    extra_headers?: Record<string, string>;
}

export interface UpdateLLMConfigRequest {
  id: number;
    custom_name: string;
    model: number;
  api_key: string;
    temperature?: number | null;
    top_p?: number | null;
    stop?: string[] | null;
    max_tokens?: number | null;
    presence_penalty?: number | null;
    frequency_penalty?: number | null;
    logit_bias?: Record<string, number> | null;
    response_format?: Record<string, unknown> | null;
    seed?: number | null;
    timeout?: number | null;
    is_visible?: boolean;
    headers?: Record<string, string>;
    extra_headers?: Record<string, string>;
}

export interface LLMConfigFormValue {
    providerId: number | null;
    modelId: number | null;
    customName: string;
    apiKey: string;
    headers: Record<string, string>;
    temperature: number | null;
    topP: number | null;
    presencePenalty: number | null;
    frequencyPenalty: number | null;
    maxTokens: number | null;
    timeout: number | null;
    seed: number | null;
    stop: string[] | null;
    logitBias: Record<string, number> | null;
    responseFormat: Record<string, unknown> | null;
}
