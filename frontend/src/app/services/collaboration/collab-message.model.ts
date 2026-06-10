export interface PresenceMessage {
    type: 'presence';
    flow_id: number;
    count: number;
}

export type CollabConnectionState = 'disconnected' | 'connecting' | 'connected';
