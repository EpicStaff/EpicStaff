import { DefaultEmbeddingConfig } from './default-embedding-config.model';
import { DefaultLLMConfig } from './default-llm-config.model';

export interface DefaultConfigBundle {
    default_agent_config: Record<string, unknown> | null;
    default_realtime_agent_config: Record<string, unknown> | null;
    default_crew_config: Record<string, unknown> | null;
    default_tool_config: Record<string, unknown> | null;
}

export interface AllDefaults extends DefaultConfigBundle {
    defaultLlm: DefaultLLMConfig | null;
    defaultEmbedding: DefaultEmbeddingConfig | null;
}
