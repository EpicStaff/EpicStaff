export const EP_CHAT_COMMANDS = {
    AGENT_CREATE: 'agent.create',
    AGENT_SELECT: 'agent.select',
    AGENT_REMOVE: 'agent.remove',
    AGENTS_SYNC: 'agents.sync',
} as const;

export type EpChatAction =
    (typeof EP_CHAT_COMMANDS)[keyof typeof EP_CHAT_COMMANDS];

export const EP_CHAT_EVENT_TYPES = {
    CHAT_CLOSED: 'chat.closed',
    CHAT_OPENED: 'chat.opened',
    APP_OPEN_FLOW: 'app.openFlow',
    APP_OPEN_NODE: 'app.openNode',
    APP_REFRESH_CACHE: 'app.refreshCache',
    APP_TOGGLE_DOCK: 'app.toggleDock',
    AGENT_DISCONNECTED: 'agent.disconnected',
} as const;

export type EpChatEventType =
    (typeof EP_CHAT_EVENT_TYPES)[keyof typeof EP_CHAT_EVENT_TYPES];

export interface EpicChatCreateAgentPayload {
    name: string;
    description?: string;
    flowId: number | string;
    flowUrl: string;
    imagePath?: string;
    selectAfterCreate?: boolean;
}

export interface EpicChatSyncAgentsPayload {
    agents: EpicChatCreateAgentPayload[];
}

export type EpChatCommandPayload =
    | EpicChatCreateAgentPayload
    | EpicChatSyncAgentsPayload
    | Record<string, unknown>;

export interface EpChatCommand {
    requestId: string;
    action: EpChatAction | string;
    payload: EpChatCommandPayload;
}

export interface EpChatCommandResult {
    requestId: string;
    action: EpChatAction | string;
    success: boolean;
    message?: string;
    payload?: Record<string, unknown>;
}

export interface EpChatEvent {
    type: string;
    payload?: Record<string, unknown>;
}
