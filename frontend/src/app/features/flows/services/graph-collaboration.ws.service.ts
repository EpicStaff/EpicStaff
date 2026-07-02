import { inject, Injectable, signal } from '@angular/core';
import { Subject } from 'rxjs';

import { ConfigService } from '../../../services/config/config.service';
import { WsTicketService } from '../../../services/auth/ws-ticket.service';

export interface EditorInfo {
    user_id: number;
    display_name: string | null;
    avatar_url?: string | null;
}

type ServerMessage = 
    | PresenceStateMessage
    | UserJoinedMessage
    | UserLeftMessage
    | GraphModifiedMessage
    | GraphSavedMessage
    | WsErrorMessage
    | PresenceStateUpdated
    

type PresenceStateMessage  = { type: 'presence_state'; editors: EditorInfo[] };
type UserJoinedMessage     = { type: 'user_joined'; editor: EditorInfo };
type UserLeftMessage       = { type: 'user_left'; user_id: number };
type PresenceStateUpdated  = { type: 'presence_state_updated'; editor: EditorInfo};
export type GraphModifiedMessage = { 
    type: 'graph_modified'; 
    graph_id: number; 
    modified_by: EditorInfo 
};
export type GraphSavedMessage    = {
    type: 'graph_saved';
    graph_id: number;
    new_save_version: number;
    saved_by: EditorInfo;
    saved_at: string;
};
type WsErrorMessage = { type: 'error'; code: string; message: string };

type ClientMessage = { type: 'graph_modified' };

type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'reconnecting';

@Injectable ({'providedIn': 'root'})

export class GraphCollaborationWsService {
    private configService = inject(ConfigService);
    private wsTicketService = inject(WsTicketService);
    private socket: WebSocket | null = null;
    private currentGraphId: number | null = null;
    private reconnectTimeout: number | null = null;
    private isManualDisconnect = false;
    private reconnectAttempts = 0;
    private readonly maxReconnectAttempts = 5;
    private readonly baseReconnectDelayMs = 1000;
    private readonly maxReconnectDelayMs = 30000;

    public editors = signal<EditorInfo[]>([]);
    public connectionStatus = signal<ConnectionStatus>('disconnected');

    public graphSaved$ = new Subject<GraphSavedMessage>();
    public graphModified$ = new Subject<GraphModifiedMessage>();

    public connect(graphId: number) {
        if (this.currentGraphId === graphId && this.socket) return;
        this.cleanUp();
        this.currentGraphId = graphId;
        this.isManualDisconnect = false;
        this.openConnection();
    }

    public disconnect(): void {
        this.isManualDisconnect = true;
        this.cleanUp();
    }

    private openConnection(): void {
        this.connectionStatus.set('connecting');

        this.wsTicketService.fetchTicket().subscribe({
            next: (ticket) => this.openSocket(ticket),
            error: (err) => {
                console.error('Failed to fetch WS ticket:', err);
                this.handleConnectionLoss();
            }
        });
    }

    private openSocket(ticket: string): void {
        const wsBase = this.configService.apiUrl
            .replace(/\/api\/$/, '')
            .replace(/^http/, 'ws');
        const url = `${wsBase}/ws/graphs/${this.currentGraphId}/edit/?ticket=${encodeURIComponent(ticket)}`;
        this.socket = new WebSocket(url);

        this.socket.onopen = () => {
            this.reconnectAttempts = 0;
            this.connectionStatus.set('connected');
            console.log('[WS] Connected to graph', this.currentGraphId);
        };

        this.socket.onmessage = (event: MessageEvent) => {
            try {
                const message = JSON.parse(event.data as string) as ServerMessage;
                this.handleMessage(message);
            } catch {
                console.error('[WS] Failed to parse message:', event.data);
            }
        }

        this.socket.onclose = (event) => {
            console.log('[WS] Closed, code:', event.code);
            this.socket = null;
            if (!this.isManualDisconnect) {
                this.handleConnectionLoss();
            }
        }

        this.socket.onerror = (err) => {
            console.error('[WS] Error:', err)
        }

    }

    private handleMessage(message: ServerMessage): void {
        switch (message.type) {
            case 'presence_state':
                this.editors.set(message.editors);
                break;
            case 'user_joined':
                this.editors.update((editors) => {
                    const exists = editors.some((e) => e.user_id === message.editor.user_id);
                    return exists ? editors : [...editors, message.editor]
                });
                break;
            case 'user_left':
                this.editors.update((editors) =>
                editors.filter((e) => e.user_id !== message.user_id)
                );
                break;
            case 'graph_modified':
                this.updateEditorInfo(message.modified_by);
                this.graphModified$.next(message);
                break;
            case 'graph_saved':
                this.updateEditorInfo(message.saved_by);
                this.graphSaved$.next(message);
                break;
            case 'error':
                console.error(`[WS] Server error [${message.code}]: ${message.message}`);
                break;
            case 'presence_state_updated':
                this.editors.update((editors) => 
                editors.map((e) => e.user_id === message.editor.user_id ? message.editor : e)
                );
                break;
        }
    }

    private handleConnectionLoss(): void {
        this.connectionStatus.set('reconnecting');
        this.socket = null;

        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error(`[WS] Max reconnect attempts reached. Giving up.`)
            this.connectionStatus.set('disconnected');
            return;
        }

        this.reconnectAttempts++;
        const delay = this.calculateReconnectDelay();

        this.reconnectTimeout = window.setTimeout(() => {
            if (!this.isManualDisconnect && this.currentGraphId !== null) {
                this.openConnection();
            }
        }, delay);

    }

    private calculateReconnectDelay(): number {
        return Math.min(
            this.baseReconnectDelayMs * Math.pow(2, this.reconnectAttempts - 1),
            this.maxReconnectDelayMs
        );
    }

    private updateEditorInfo(editor: EditorInfo): void {
        this.editors.update((list) => {
            const idx = list.findIndex((e) => e.user_id === editor.user_id);
            if (idx === -1) return list;
            const updated = [...list];
            updated[idx] = editor;
            return updated;
        });
    }

    public sendUserEditing(): void {
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket?.send(JSON.stringify({type: 'graph_modified'}))
        }
    }

    private cleanUp():void {
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
        this.reconnectAttempts = 0;
        this.currentGraphId = null;
        this.editors.set([]);
        this.connectionStatus.set('disconnected');
    }

}
