/**
 * How a provider's name reads in the UI. The backend keys providers by a lowercase id (`openai`, `aws_sagemaker`),
 * so brand casing lives here; keyed like `PROVIDER_ICON_PATHS`.
 */
export const PROVIDER_DISPLAY_NAMES: Partial<Record<string, string>> = {
    ai21: 'AI21',
    'aleph-alpha': 'Aleph Alpha',
    anthropic: 'Anthropic',
    anyscale: 'Anyscale',
    aws_sagemaker: 'AWS SageMaker',
    azure: 'Azure',
    azure_ai: 'Azure AI',
    bedrock: 'Bedrock',
    clarifai: 'Clarifai',
    cloudflare_workers_ai: 'Cloudflare Workers AI',
    cohere: 'Cohere',
    compactifai: 'CompactifAI',
    dashscope: 'DashScope',
    databricks: 'Databricks',
    deepinfra: 'DeepInfra',
    deepseek: 'DeepSeek',
    elevenlabs: 'ElevenLabs',
    'featherless-ai': 'Featherless AI',
    fireworks_ai: 'Fireworks AI',
    friendliai: 'FriendliAI',
    galadriel: 'Galadriel',
    gemini: 'Gemini',
    github: 'GitHub',
    google_ai: 'Google AI',
    groq: 'Groq',
    heroku: 'Heroku',
    huggingface: 'Hugging Face',
    hyperbolic: 'Hyperbolic',
    lambda_ai: 'Lambda AI',
    meta_llama: 'Meta Llama',
    mistral: 'Mistral',
    morph: 'Morph',
    novita: 'Novita',
    novita_ai: 'Novita AI',
    nvidia_nim: 'NVIDIA NIM',
    oci: 'OCI',
    ollama: 'Ollama',
    openai: 'OpenAI',
    openrouter: 'OpenRouter',
    perplexity: 'Perplexity',
    petals: 'Petals',
    replicate: 'Replicate',
    sambanova: 'SambaNova',
    'together-ai': 'Together AI',
    v0: 'v0',
    vertex_ai: 'Vertex AI',
    vllm: 'vLLM',
    voyage: 'Voyage',
    watsonx: 'watsonx',
    xinference: 'Xinference',
};

/** A provider's UI name: its brand name when known, else the id with separators as spaces and each word capitalised. */
export function providerDisplayName(providerId: string): string {
    const known = PROVIDER_DISPLAY_NAMES[providerId.toLowerCase()];
    if (known) return known;
    return providerId
        .split(/[-_\s]+/)
        .filter((word) => word.length > 0)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}
