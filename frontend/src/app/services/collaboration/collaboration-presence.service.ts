import { inject, Injectable, signal } from '@angular/core';

import { AuthService } from '../auth/auth.service';
import { ConfigService } from '../config/config.service';
import { CollabConnectionState, PresenceMessage } from './collab-message.model';

const RECONNECT_DELAY_MS = 3_000;

@Injectable({ providedIn: 'root' })
export class CollaborationPresenceService {
    readonly participantCount = signal<number>(0);
    readonly connectionState = signal<CollabConnectionState>('disconnected');

    private readonly authService = inject(AuthService);
    private readonly configService = inject(ConfigService);

    private socket: WebSocket | null = null;
    private connectedFlowId: number | null = null;
    private intentionalClose = false;
    private reconnectTimerId: ReturnType<typeof setTimeout> | null = null;

    connect(flowId: number): void {
        if (this.socket !== null) {
            if (this.connectedFlowId === flowId) {
                return;
            }
            this.disconnect();
        }

        this.openSocket(flowId);
    }

    disconnect(): void {
        this.intentionalClose = true;
        this.cancelPendingReconnect();
        this.closeSocket();
        this.participantCount.set(0);
        this.connectionState.set('disconnected');
        this.connectedFlowId = null;
    }

    private openSocket(flowId: number): void {
        const url = this.buildWebSocketUrl(flowId);
        if (url === null) {
            return;
        }

        this.intentionalClose = false;
        this.connectedFlowId = flowId;
        this.connectionState.set('connecting');

        const webSocket = new WebSocket(url);
        this.socket = webSocket;

        webSocket.onopen = (): void => {
            if (this.socket === webSocket) {
                this.connectionState.set('connected');
            }
        };

        webSocket.onmessage = (event: MessageEvent): void => {
            this.handleMessage(event);
        };

        webSocket.onclose = (): void => {
            if (this.socket !== webSocket) {
                return;
            }
            this.socket = null;

            if (this.intentionalClose) {
                return;
            }

            this.connectionState.set('disconnected');
            this.scheduleReconnect(flowId);
        };

        webSocket.onerror = (): void => {
            // The close event fires immediately after an error, so no additional
            // state updates are needed here. The close handler drives recovery.
        };
    }

    private handleMessage(event: MessageEvent): void {
        let parsed: unknown;
        try {
            parsed = JSON.parse(event.data as string);
        } catch {
            return;
        }

        if (!isPresenceMessage(parsed)) {
            return;
        }

        this.participantCount.set(parsed.count);
    }

    private scheduleReconnect(flowId: number): void {
        this.cancelPendingReconnect();
        this.reconnectTimerId = setTimeout(() => {
            this.reconnectTimerId = null;
            if (this.intentionalClose) {
                return;
            }
            this.attemptReconnect(flowId);
        }, RECONNECT_DELAY_MS);
    }

    private attemptReconnect(flowId: number): void {
        const url = this.buildWebSocketUrl(flowId);
        if (url === null) {
            return;
        }

        this.connectedFlowId = flowId;
        this.connectionState.set('connecting');

        const webSocket = new WebSocket(url);
        this.socket = webSocket;

        webSocket.onopen = (): void => {
            if (this.socket === webSocket) {
                this.connectionState.set('connected');
            }
        };

        webSocket.onmessage = (event: MessageEvent): void => {
            this.handleMessage(event);
        };

        webSocket.onclose = (): void => {
            if (this.socket !== webSocket) {
                return;
            }
            this.socket = null;

            if (!this.intentionalClose) {
                // Reconnect attempt also failed — stay disconnected per spec.
                this.connectionState.set('disconnected');
                this.connectedFlowId = null;
            }
        };

        webSocket.onerror = (): void => {
            // Handled by onclose.
        };
    }

    private closeSocket(): void {
        if (this.socket !== null) {
            this.socket.onopen = null;
            this.socket.onmessage = null;
            this.socket.onclose = null;
            this.socket.onerror = null;
            this.socket.close();
            this.socket = null;
        }
    }

    private cancelPendingReconnect(): void {
        if (this.reconnectTimerId !== null) {
            clearTimeout(this.reconnectTimerId);
            this.reconnectTimerId = null;
        }
    }

    private buildWebSocketUrl(flowId: number): string | null {
        const token = this.authService.getAccessToken();
        if (!token) {
            return null;
        }

        const realtimeBase = this.configService.realtimeApiUrl;
        const wsBase = realtimeBase.replace(/^https:\/\//i, 'wss://').replace(/^http:\/\//i, 'ws://');
        const normalizedBase = wsBase.endsWith('/') ? wsBase : `${wsBase}/`;

        return `${normalizedBase}collab/?flow_id=${flowId}&token=${encodeURIComponent(token)}`;
    }
}

function isPresenceMessage(value: unknown): value is PresenceMessage {
    return (
        typeof value === 'object' &&
        value !== null &&
        (value as Record<string, unknown>)['type'] === 'presence' &&
        typeof (value as Record<string, unknown>)['flow_id'] === 'number' &&
        typeof (value as Record<string, unknown>)['count'] === 'number'
    );
}
