import { AgentDefinition } from '../../../features/agent-definitions/models/agent-definition.model';
import { RealtimeAgentDefinition } from '../../../features/agent-definitions/models/realtime-agent-definition.model';

// An agent definition plus its realtime row. Without a provider config on that
// row the definition cannot connect, so it never reaches the list.
export interface ChatAgent {
    agent: AgentDefinition;
    realtime: RealtimeAgentDefinition;
}

// Display-only projection. Never stored — derived from a ChatAgent so templates
// never reach into the nested shape.
export interface ChatAgentVM {
    id: number;
    title: string;
    realtimeConfigId: number | null;
    modelName: string | null;
    customName: string | null;
}

// Payload for POST /init-realtime/. The backend requires agent_definition_id.
export interface InitRealtimePayload {
    agent_definition_id: number;
}

export function chatAgentTitle(a: ChatAgent): string {
    return a.agent.name;
}

export function chatAgentRealtimeConfigId(a: ChatAgent): number | null {
    return a.realtime.openai_config ?? a.realtime.elevenlabs_config ?? a.realtime.gemini_config ?? null;
}

export function toInitRealtimePayload(a: ChatAgent): InitRealtimePayload {
    return { agent_definition_id: a.agent.id };
}

export function sameChatAgent(a: ChatAgent | null, b: ChatAgent | null): boolean {
    if (!a || !b) return false;
    return a.agent.id === b.agent.id;
}
