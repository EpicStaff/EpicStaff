export const PROVIDER_ICON_PATHS: Record<string, string> = {
    openai: 'llm-openai',
    anthropic: 'llm-claude',
    ollama: 'llm-ollama',
    huggingface: 'llm-huggingface',
    groq: 'llm-groq',
    azure: 'llm-azure',
    gemini: 'llm-gemini',
    cohere: 'llm-cohere',
    mistral: 'llm-mistral',
    typesafe: 'llm-typesafe',

    // Default icon
    default: 'logo',
};

/** One-colour logos (their fill follows CSS `color`), for providers that have one; keyed like `PROVIDER_ICON_PATHS`. */
export const PROVIDER_MONOCHROME_ICON_PATHS: Partial<Record<string, string>> = {
    openai: 'llm-openai-mono',
    ollama: 'llm-ollama-mono',
    anthropic: 'llm-anthropic-mono',
};
