// Realtime (voice) settings for an AgentDefinition. One-to-one: the primary key
// is the agent definition id. Presence of this row = "voice enabled" for the agent.
export interface RealtimeAgentDefinition {
    agent_definition: number;
    openai_config: number | null;
    elevenlabs_config: number | null;
    gemini_config: number | null;
    voice: string;
    wake_word: string | null;
    stop_prompt: string | null;
    language: string | null;
    voice_recognition_prompt: string | null;
}

export interface CreateRealtimeAgentDefinitionRequest {
    agent_definition: number;
    openai_config?: number | null;
    elevenlabs_config?: number | null;
    gemini_config?: number | null;
    voice?: string;
    wake_word?: string | null;
    stop_prompt?: string | null;
    language?: string | null;
    voice_recognition_prompt?: string | null;
}

export type PartialUpdateRealtimeAgentDefinitionRequest = Partial<CreateRealtimeAgentDefinitionRequest>;
