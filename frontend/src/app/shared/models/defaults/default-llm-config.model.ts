export interface DefaultLLMConfig {
    id: number;
    model: number | null;
    temperature: number | null;
    top_p: number | null;
    stop: unknown | null;
    max_tokens: number | null;
    presence_penalty: number | null;
    frequency_penalty: number | null;
    logit_bias: unknown | null;
    response_format: unknown | null;
    seed: number | null;
    api_key: string | null;
    headers: Record<string, unknown>;
    extra_headers: Record<string, unknown>;
    timeout: number | null;
    is_visible: boolean;
}
