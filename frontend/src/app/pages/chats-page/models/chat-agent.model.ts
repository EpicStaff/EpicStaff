import { AgentDefinition } from '../../../features/agent-definitions/models/agent-definition.model';
import { RealtimeAgentDefinition } from '../../../features/agent-definitions/models/realtime-agent-definition.model';
import { FullAgent } from '../../../features/staff/services/full-agent.service';

export type ChatAgentKind = 'staff' | 'definition';

// The selectable entity behind a chat. Staff agents carry realtime config inline
// (realtime_agent), agent definitions carry it in a separate 1-to-1 row whose
// presence is what makes the definition eligible for the Agents tab.
export type ChatAgent =
    | { kind: 'staff'; agent: FullAgent }
    | { kind: 'definition'; agent: AgentDefinition; realtime: RealtimeAgentDefinition };

// Display-only projection. Never stored — derived from a ChatAgent so templates
// never branch on kind.
export interface ChatAgentVM {
    kind: ChatAgentKind;
    id: number;
    title: string;
    realtimeConfigId: number | null;
    transcriptionConfigId: number | null;
    modelName: string | null;
    customName: string | null;
}

// Payload for POST /init-realtime/. The backend requires exactly one of the two ids.
export type InitRealtimePayload = { agent_id: number } | { agent_definition_id: number };

export function chatAgentId(a: ChatAgent): number {
    return a.agent.id;
}

export function chatAgentTitle(a: ChatAgent): string {
    return a.kind === 'staff' ? a.agent.role : a.agent.name;
}

export function chatAgentRealtimeConfigId(a: ChatAgent): number | null {
    return a.kind === 'staff' ? (a.agent.realtime_agent?.realtime_config ?? null) : a.realtime.realtime_config;
}

export function chatAgentTranscriptionConfigId(a: ChatAgent): number | null {
    return a.kind === 'staff'
        ? (a.agent.realtime_agent?.realtime_transcription_config ?? null)
        : a.realtime.realtime_transcription_config;
}

export function toInitRealtimePayload(a: ChatAgent): InitRealtimePayload {
    return a.kind === 'staff' ? { agent_id: a.agent.id } : { agent_definition_id: a.agent.id };
}

// Same identity iff same kind AND same id — staff and definition id-spaces overlap.
export function sameChatAgent(a: ChatAgent | null, b: ChatAgent | null): boolean {
    if (!a || !b) return false;
    return a.kind === b.kind && a.agent.id === b.agent.id;
}
