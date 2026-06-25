import { inject, Injectable, signal } from '@angular/core';
import { IPoint } from '@foblex/2d';
import { Subject } from 'rxjs';
import { debounceTime, filter, throttleTime } from 'rxjs';
import { NodeType } from 'src/app/visual-programming/core/enums/node-type';

import { ProfileService } from '../../../services/auth/profile.service';
import { WsTicketService } from '../../../services/auth/ws-ticket.service';
import { ConfigService } from '../../../services/config/config.service';
import { ConnectionModel } from '../../../visual-programming/core/models/connection.model';
import { NodeModel } from '../../../visual-programming/core/models/node.model';
import { GraphDto } from '../models/graph.model';

export interface EditorInfo {
    user_id: number;
    display_name: string | null;
    avatar_url?: string | null;
}

export interface EntryDeleteRef {
    list_key: string;
    id?: number;
    temp_id?: string;
}

type ServerMessage =
    | PresenceStateMessage
    | UserJoinedMessage
    | UserLeftMessage
    | GraphStateMessage
    | GraphSavedMessage
    | WsErrorMessage
    | NodeCreatedMessage
    | NodeUpdatedMessage
    | NodesDeletedMessage
    | ConnectionCreatedMessage
    | ConnectionDeletedMessage
    | ConnectionsDeletedMessage
    | ConnectionWaypointsUpdatedMessage
    | CursorMovedMessage
    | CursorBatchMessage
    | SelectionChangedMessage
    | NodeLockedMessage
    | NodeUnlockedMessage
    | LockStateMessage;

type PresenceStateMessage = { type: 'presence_state'; editors: EditorInfo[] };
type UserJoinedMessage = { type: 'user_joined'; editor: EditorInfo };
type UserLeftMessage = { type: 'user_left'; user_id: number };
type WsErrorMessage = { type: 'error'; code: string; message: string };

export type GraphStateMessage = { type: 'graph_state'; flow: GraphDto };
export type NodeCreatedMessage = { type: 'node_created'; node: NodeModel; editor: EditorInfo };
export type NodeUpdatedMessage = { type: 'node_updated'; node: NodeModel; editor: EditorInfo };
export type NodesDeletedMessage = { type: 'nodes_deleted'; refs: EntryDeleteRef[]; editor: EditorInfo };
export type ConnectionCreatedMessage = { type: 'connection_created'; connection: ConnectionModel; editor: EditorInfo };
export type ConnectionDeletedMessage = {
    type: 'connection_deleted';
    connection_id: number | null;
    temp_id: string | null;
    list_key: string;
    editor: EditorInfo;
};
export type ConnectionsDeletedMessage = { type: 'connections_deleted'; refs: EntryDeleteRef[]; editor: EditorInfo };
export type ConnectionWaypointsUpdatedMessage = {
    type: 'connection_waypoints_updated';
    connection_id: string;
    waypoints: IPoint[];
    editor: EditorInfo;
};
export type CursorMovedMessage = { type: 'cursor_moved'; x: number; y: number; editor: EditorInfo };
export type CursorData = { x: number; y: number; editor: EditorInfo };
export type CursorBatchMessage = { type: 'cursor_batch'; cursors: CursorData[] };
export type SelectionChangedMessage = { type: 'selection_changed'; node_ids: string[]; editor: EditorInfo };
export type NodeLockedMessage = { type: 'node_locked'; node_id: string; field: string; editor: EditorInfo };
export type NodeUnlockedMessage = { type: 'node_unlocked'; node_id: string; field: string; editor: EditorInfo };
export type LockStateMessage = { type: 'lock_state'; locks: Record<string, Record<string, EditorInfo>> };

export type GraphSavedMessage = {
    type: 'graph_saved';
    graph_id: number;
    new_save_version: number;
    saved_by: EditorInfo;
    saved_at: string;
};

type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'reconnecting';

export function nodeTypeToListKey(type: NodeType): string | null {
    switch (type) {
        case NodeType.AGENT:
        case NodeType.TASK:
        case NodeType.PROJECT:
            return 'crew_node_list';
        case NodeType.PYTHON:
            return 'python_node_list';
        case NodeType.FILE_EXTRACTOR:
            return 'file_extractor_node_list';
        case NodeType.AUDIO_TO_TEXT:
            return 'audio_transcription_node_list';
        case NodeType.START:
            return 'start_node_list';
        case NodeType.END:
            return 'end_node_list';
        case NodeType.SUBGRAPH:
            return 'subgraph_node_list';
        case NodeType.TABLE:
            return 'decision_table_node_list';
        case NodeType.NOTE:
            return 'graph_note_list';
        case NodeType.WEBHOOK_TRIGGER:
            return 'webhook_trigger_node_list';
        case NodeType.TELEGRAM_TRIGGER:
            return 'telegram_trigger_node_list';
        case NodeType.SCHEDULE_TRIGGER:
            return 'schedule_trigger_node_list';
        case NodeType.CODE_AGENT:
            return 'code_agent_node_list';
        case NodeType.EDGE:
            return 'conditional_edge_list';
        default:
            console.warn(`[WS] No list_key for NodeType: ${type}`);
            return null;
    }
}

@Injectable({ providedIn: 'root' })
export class GraphCollaborationWsService {
    private configService = inject(ConfigService);
    private wsTicketService = inject(WsTicketService);
    private profileService = inject(ProfileService);
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
    public readonly lockedNodeFields = signal<Map<string, Map<string, EditorInfo>>>(new Map());

    public graphSaved$ = new Subject<GraphSavedMessage>();
    public graphState$ = new Subject<GraphStateMessage>();
    public nodeCreated$ = new Subject<NodeCreatedMessage>();
    public nodeUpdated$ = new Subject<NodeUpdatedMessage>();
    public nodesDeleted$ = new Subject<NodesDeletedMessage>();
    public connectionCreated$ = new Subject<ConnectionCreatedMessage>();
    public connectionDeleted$ = new Subject<ConnectionDeletedMessage>();
    public connectionsDeleted$ = new Subject<ConnectionsDeletedMessage>();
    public connectionWaypointsUpdated$ = new Subject<ConnectionWaypointsUpdatedMessage>();
    public cursorMoved$ = new Subject<CursorMovedMessage>();
    public selectionChanged$ = new Subject<SelectionChangedMessage>();
    public nodeLocked$ = new Subject<NodeLockedMessage>();
    public nodeUnlocked$ = new Subject<NodeUnlockedMessage>();

    private readonly cursorPipe$ = new Subject<{ x: number; y: number }>();
    private readonly waypointPipe$ = new Subject<{ connection_id: string; waypoints: IPoint[]; listKey: string }>();
    private lastNodeDragSendAt = 0;
    private lastSentCursorX = 0;
    private lastSentCursorY = 0;

    constructor() {
        this.cursorPipe$
            .pipe(
                filter(
                    ({ x, y }) => Math.abs(x - this.lastSentCursorX) >= 5 || Math.abs(y - this.lastSentCursorY) >= 5
                ),
                throttleTime(150)
            )
            .subscribe(({ x, y }) => {
                this.lastSentCursorX = x;
                this.lastSentCursorY = y;
                const editor = this.buildEditorInfo();
                if (editor) this.sendRaw({ type: 'cursor_moved', x, y, editor });
            });

        this.waypointPipe$.pipe(debounceTime(200)).subscribe(({ connection_id, waypoints, listKey }) => {
            const editor = this.buildEditorInfo();
            if (editor)
                this.sendRaw({
                    type: 'connection_waypoints_updated',
                    connection_id,
                    waypoints,
                    list_key: listKey,
                    editor,
                });
        });
    }
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
            },
        });
    }

    private openSocket(ticket: string): void {
        const wsBase = this.configService.apiUrl.replace(/\/api\/$/, '').replace(/^http/, 'ws');
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
        };

        this.socket.onclose = (event) => {
            console.log('[WS] Closed, code:', event.code);
            this.socket = null;
            if (!this.isManualDisconnect) {
                this.handleConnectionLoss();
            }
        };

        this.socket.onerror = (err) => {
            console.error('[WS] Error:', err);
        };
    }

    private handleMessage(message: ServerMessage): void {
        switch (message.type) {
            case 'presence_state':
                this.editors.set(message.editors);
                break;
            case 'user_joined':
                this.editors.update((editors) =>
                    editors.some((e) => e.user_id === message.editor.user_id) ? editors : [...editors, message.editor]
                );
                break;
            case 'user_left':
                this.editors.update((editors) => editors.filter((e) => e.user_id !== message.user_id));
                //remove all users field lockings
                this.lockedNodeFields.update((m) => {
                    const next = new Map(m);
                    for (const [nodeId, fields] of next) {
                        const filtered = new Map([...fields].filter(([, e]) => e.user_id !== message.user_id));
                        if (filtered.size === 0) next.delete(nodeId);
                        else next.set(nodeId, filtered);
                    }
                    return next;
                });
                break;
            case 'lock_state':
                this.lockedNodeFields.set(
                    new Map(
                        Object.entries(message.locks).map(([nodeId, fields]) => [
                            nodeId,
                            new Map(Object.entries(fields)),
                        ])
                    )
                );
                break;
            case 'graph_state':
                this.graphState$.next(message);
                break;
            case 'graph_saved':
                this.graphSaved$.next(message);
                break;
            case 'node_created':
                this.nodeCreated$.next(message);
                break;
            case 'node_updated':
                this.nodeUpdated$.next(message);
                break;
            case 'nodes_deleted':
                this.nodesDeleted$.next(message);
                break;
            case 'connection_created':
                this.connectionCreated$.next(message);
                break;
            case 'connection_deleted':
                this.connectionDeleted$.next(message);
                break;
            case 'connections_deleted':
                this.connectionsDeleted$.next(message);
                break;
            case 'connection_waypoints_updated':
                this.connectionWaypointsUpdated$.next(message);
                break;
            case 'cursor_moved':
                this.cursorMoved$.next(message);
                break;
            case 'cursor_batch':
                if (Array.isArray(message.cursors)) {
                    for (const cursor of message.cursors) {
                        this.cursorMoved$.next({
                            type: 'cursor_moved',
                            x: cursor.x,
                            y: cursor.y,
                            editor: cursor.editor,
                        });
                    }
                }
                break;
            case 'selection_changed':
                this.selectionChanged$.next(message);
                break;
            case 'node_locked':
                this.lockedNodeFields.update((m) => {
                    const next = new Map(m);
                    const nodeFields = new Map(next.get(message.node_id) ?? []);
                    nodeFields.set(message.field, message.editor);
                    next.set(message.node_id, nodeFields);
                    return next;
                });
                this.nodeLocked$.next(message);
                break;
            case 'node_unlocked':
                this.lockedNodeFields.update((m) => {
                    const next = new Map(m);
                    const nodeFields = new Map(next.get(message.node_id) ?? []);
                    nodeFields.delete(message.field);
                    if (nodeFields.size === 0) next.delete(message.node_id);
                    else next.set(message.node_id, nodeFields);
                    return next;
                });
                this.nodeUnlocked$.next(message);
                break;
            case 'error':
                console.error(`[WS] Server error [${message.code}]: ${message.message}`);
                break;
        }
    }

    public sendNodeCreated(node: NodeModel): void {
        const list_key = nodeTypeToListKey(node.type);
        if (!list_key) return;
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'node_created', node, list_key, editor });
    }

    public sendNodeUpdated(node: NodeModel): void {
        const list_key = nodeTypeToListKey(node.type);
        if (!list_key) return;
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'node_updated', node, list_key, editor });
    }

    public sendNodePositionDuringDrag(node: NodeModel): void {
        const now = Date.now();
        if (now - this.lastNodeDragSendAt < 150) return;
        this.lastNodeDragSendAt = now;
        const list_key = nodeTypeToListKey(node.type);
        if (!list_key) return;
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'node_updated', node, list_key, editor });
    }

    public sendNodesDeleted(refs: EntryDeleteRef[]): void {
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'nodes_deleted', refs, editor });
    }

    public sendConnectionCreated(connection: ConnectionModel, listKey: string): void {
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'connection_created', connection, list_key: listKey, editor });
    }

    public sendConnectionDeleted(ref: EntryDeleteRef): void {
        const editor = this.buildEditorInfo();
        if (editor)
            this.sendRaw({
                type: 'connection_deleted',
                connection_id: ref.id ?? null,
                temp_id: ref.temp_id ?? null,
                list_key: ref.list_key,
                editor,
            });
    }

    public sendConnectionsDeleted(refs: EntryDeleteRef[]): void {
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'connections_deleted', refs, editor });
    }

    public sendConnectionWaypointsUpdated(connection_id: string, waypoints: IPoint[], listKey: string): void {
        this.waypointPipe$.next({ connection_id, waypoints, listKey });
    }

    public sendCursorMoved(x: number, y: number): void {
        this.cursorPipe$.next({ x, y });
    }

    public sendSelectionChanged(node_ids: string[]): void {
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'selection_changed', node_ids, editor });
    }

    public sendNodeLocked(node_id: string, field: string): void {
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'node_locked', node_id, field, editor });
    }

    public sendNodeUnlocked(node_id: string, field: string): void {
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'node_unlocked', node_id, field, editor });
    }

    private buildEditorInfo(): EditorInfo | null {
        const user = this.profileService.currentUserSignal();
        if (!user) return null;
        return { user_id: user.id, display_name: user.display_name, avatar_url: user.avatar_url };
    }

    private sendRaw(payload: object): void {
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(payload));
        }
    }

    private handleConnectionLoss(): void {
        this.connectionStatus.set('reconnecting');
        this.socket = null;

        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error(`[WS] Max reconnect attempts reached. Giving up.`);
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
        return Math.min(this.baseReconnectDelayMs * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelayMs);
    }

    private cleanUp(): void {
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
        this.lockedNodeFields.set(new Map());
    }
}
