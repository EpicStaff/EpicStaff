import { computed, inject, Injectable, signal } from '@angular/core';
import { IPoint } from '@foblex/2d';
import { Subject } from 'rxjs';
import { debounceTime, filter, throttleTime } from 'rxjs';
import { NodeType } from 'src/app/visual-programming/core/enums/node-type';
import { buildPartialNodePayload } from 'src/app/visual-programming/utils/save/partial-node-broadcast';

import { ProfileService } from '../../../services/auth/profile.service';
import { WsTicketService } from '../../../services/auth/ws-ticket.service';
import { ConfigService } from '../../../services/config/config.service';
import { ConnectionModel } from '../../../visual-programming/core/models/connection.model';
import { NodeModel } from '../../../visual-programming/core/models/node.model';
import {
    AudioToTextNodeModel,
    ClassificationDecisionTableNodeModel,
    CodeAgentNodeModel,
    DecisionTableNodeModel,
    EdgeNodeModel,
    EndNodeModel,
    FileExtractorNodeModel,
    GraphNoteModel,
    PythonNodeModel,
    ScheduleTriggerNodeModel,
    StartNodeModel,
    SubGraphNodeModel,
    TelegramTriggerNodeModel,
    WebhookTriggerNodeModel,
} from '../../../visual-programming/core/models/node.model';
import { toNodeMetadata } from '../../../visual-programming/utils/save/metadata';
import { buildCdtNodePayload } from '../../../visual-programming/utils/save/payload';
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
    | LockStateMessage
    | SaveFailedMessage
    | PresenceStateUpdated
    | GraphFilesChangedMessage
    | OpRejectedMessage;

type PresenceStateMessage = { type: 'presence_state'; editors: EditorInfo[] };
type UserJoinedMessage = { type: 'user_joined'; editor: EditorInfo };
type UserLeftMessage = { type: 'user_left'; user_id: number };
type PresenceStateUpdated = { type: 'presence_state_updated'; editor: EditorInfo };
type WsErrorMessage = { type: 'error'; code: string; message: string };

export type SaveFailedMessage = {
    type: 'save_failed';
    graph_id: number;
    reason: string;
    saved_at: string;
};
export type GraphStateMessage = {
    type: 'graph_state';
    flow: GraphDto;
    restored_by?: EditorInfo;
    version_name?: string;
    new_save_version?: number;
};
export type NodeCreatedMessage = {
    type: 'node_created';
    node: Record<string, unknown>;
    list_key: string;
    editor: EditorInfo;
};
export type NodeUpdatedMessage = {
    type: 'node_updated';
    node: Record<string, unknown>;
    list_key: string;
    editor: EditorInfo;
    changed_fields?: string[];
    op_id?: string;
};
export type OpRejectedMessage = {
    type: 'op_rejected';
    op_type: string;
    op_id: string | null;
    list_key: string;
    node_ref: { id: number | null; temp_id: string | null };
    reason: string;
    details: Record<string, unknown> | null;
};
export type NodesDeletedMessage = { type: 'nodes_deleted'; refs: EntryDeleteRef[]; editor: EditorInfo };
export type ConnectionCreatedMessage = {
    type: 'connection_created';
    connection: Record<string, unknown>;
    list_key: string;
    editor: EditorInfo;
};
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
    connection_id: number | string;
    waypoints: IPoint[];
    list_key: string;
    editor: EditorInfo;
};
export type CursorMovedMessage = { type: 'cursor_moved'; x: number; y: number; editor: EditorInfo };
export type CursorData = { x: number; y: number; editor: EditorInfo };
export type CursorBatchMessage = { type: 'cursor_batch'; cursors: CursorData[] };
export type SelectionChangedMessage = { type: 'selection_changed'; node_ids: string[]; editor: EditorInfo };
export type NodeLockedMessage = { type: 'node_locked'; node_id: string; field: string; editor: EditorInfo };
export type NodeUnlockedMessage = { type: 'node_unlocked'; node_id: string; field: string; editor: EditorInfo };
export type LockStateMessage = { type: 'lock_state'; locks: Record<string, Record<string, EditorInfo>> };
export type GraphFilesChangedMessage = { type: 'graph_files_changed'; graph_id: number; editor: EditorInfo | null };

export type GraphSavedMessage = {
    type: 'graph_saved';
    graph_id: number;
    new_save_version: number;
    saved_by: EditorInfo;
    saved_at: string;
    temp_id_map: Record<string, number>;
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
        case NodeType.CLASSIFICATION_TABLE:
            return 'classification_decision_table_node_list';
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

// export function nodeToWsPayload(node: NodeModel): Record<string, unknown> {
//     const { id, backendId, ...rest } = node as unknown as Record<string, unknown>;
//     return backendId != null ? { ...rest, id: backendId } : { ...rest, temp_id: id };
// }

export function buildNodeBackendPayload(
    node: NodeModel,
    graphId: number,
    allNodes: NodeModel[] = [],
    // CDT routing (default/error/per-group next_node) is resolved by scanning
    // canvas connections — same as the REST bulk-save path in payload.ts.
    connections: ConnectionModel[] = []
): Record<string, unknown> | null {
    const idField = node.backendId != null ? { id: node.backendId } : { temp_id: node.id };
    const meta = toNodeMetadata(node);

    switch (node.type) {
        case NodeType.START:
            return {
                ...idField,
                graph: graphId,
                variables: (node as StartNodeModel).data.initialState ?? {},
                metadata: meta,
            };

        case NodeType.END:
            return {
                ...idField,
                graph: graphId,
                output_map: (node as EndNodeModel).data.output_map ?? { context: 'variables.context' },
                metadata: meta,
            };

        case NodeType.PYTHON: {
            const pn = node as PythonNodeModel;
            const { use_storage, ...pythonCode } = pn.data;
            return {
                ...idField,
                node_name: pn.node_name,
                graph: graphId,
                python_code: pythonCode,
                input_map: pn.input_map || {},
                output_variable_path: pn.output_variable_path || null,
                stream_config: pn.stream_config ?? {},
                use_storage: use_storage ?? false,
                test_input: pn.test_input ?? {},
                metadata: meta,
            };
        }

        case NodeType.AGENT:
        case NodeType.TASK:
        case NodeType.PROJECT: {
            const cn = node as {
                node_name: string;
                data: { id: number };
                input_map: Record<string, unknown>;
                output_variable_path: string | null;
                stream_config?: Record<string, unknown>;
            } & NodeModel;
            return {
                ...idField,
                node_name: cn.node_name,
                graph: graphId,
                crew_id: cn.data.id,
                input_map: cn.input_map || {},
                output_variable_path: cn.output_variable_path || null,
                stream_config: cn.stream_config ?? {},
                metadata: meta,
            };
        }

        case NodeType.FILE_EXTRACTOR:
            return {
                ...idField,
                node_name: (node as FileExtractorNodeModel).node_name,
                graph: graphId,
                input_map: node.input_map || {},
                output_variable_path: node.output_variable_path || null,
                metadata: meta,
            };

        case NodeType.AUDIO_TO_TEXT:
            return {
                ...idField,
                node_name: (node as AudioToTextNodeModel).node_name,
                graph: graphId,
                input_map: node.input_map || {},
                output_variable_path: node.output_variable_path || null,
                metadata: meta,
            };

        case NodeType.SUBGRAPH: {
            const sn = node as SubGraphNodeModel;
            return {
                ...idField,
                node_name: sn.node_name,
                graph: graphId,
                subgraph: sn.data.id,
                subgraph_detail: sn.data,
                input_map: sn.input_map || {},
                output_variable_path: sn.output_variable_path || null,
                metadata: meta,
            };
        }

        case NodeType.WEBHOOK_TRIGGER: {
            const wn = node as WebhookTriggerNodeModel;
            return {
                ...idField,
                node_name: wn.node_name,
                graph: graphId,
                python_code: wn.data.python_code,
                input_map: wn.input_map || {},
                output_variable_path: wn.output_variable_path || null,
                webhook_trigger_path: '',
                webhook_trigger: wn.data.webhook_trigger,
                metadata: meta,
            };
        }

        case NodeType.TELEGRAM_TRIGGER: {
            const tn = node as TelegramTriggerNodeModel;
            return {
                ...idField,
                node_name: tn.node_name,
                graph: graphId,
                telegram_bot_api_key: tn.data.telegram_bot_api_key,
                webhook_trigger: tn.data.webhook_trigger,
                fields: tn.data.fields,
                metadata: meta,
            };
        }

        case NodeType.SCHEDULE_TRIGGER: {
            const sched = node as ScheduleTriggerNodeModel;
            return {
                ...idField,
                node_name: sched.node_name,
                graph: graphId,
                is_active: sched.data.startDateTime ? sched.data.isActive : false,
                metadata: meta,
                schedule: sched.data.startDateTime ? buildSchedulePayload(sched) : null,
            };
        }

        case NodeType.NOTE: {
            const nn = node as GraphNoteModel;
            return {
                ...idField,
                node_name: nn.node_name,
                graph: graphId,
                content: nn.data.content,
                metadata: { ...meta, backgroundColor: nn.data.backgroundColor ?? null },
            };
        }

        case NodeType.CODE_AGENT: {
            const ca = node as CodeAgentNodeModel;
            return {
                ...idField,
                node_name: ca.node_name,
                graph: graphId,
                llm_config: ca.data?.llm_config_id ?? null,
                agent_mode: ca.data?.agent_mode ?? 'code_interpreter',
                session_id: ca.data?.session_id ?? '',
                system_prompt: ca.data?.system_prompt ?? '',
                stream_handler_code: ca.data?.stream_handler_code ?? '',
                libraries: ca.data?.libraries ?? [],
                polling_interval_ms: ca.data?.polling_interval_ms ?? 100,
                silence_indicator_s: ca.data?.silence_indicator_s ?? 3,
                indicator_repeat_s: ca.data?.indicator_repeat_s ?? 5,
                chunk_timeout_s: ca.data?.chunk_timeout_s ?? 30,
                inactivity_timeout_s: ca.data?.inactivity_timeout_s ?? 120,
                max_wait_s: ca.data?.max_wait_s ?? 300,
                input_map: ca.input_map,
                output_variable_path: ca.output_variable_path,
                stream_config: ca.stream_config ?? {},
                output_schema: ca.data?.output_schema ?? {},
                use_storage: ca.data?.use_storage ?? false,
                metadata: meta,
            };
        }

        case NodeType.TABLE: {
            const dn = node as DecisionTableNodeModel;
            return buildDecisionTableBackendPayload(dn, graphId, allNodes);
        }

        case NodeType.CLASSIFICATION_TABLE: {
            const cdn = node as ClassificationDecisionTableNodeModel;
            // Full bulk-save payload (prompt_configs, condition_groups, routing refs) —
            // reuses the REST save builder; resolveNodeRef falls back to allNodes lookup,
            // so an empty idMap is fine here.
            return {
                ...idField,
                ...buildCdtNodePayload(cdn, graphId, allNodes, new Map(), connections),
            };
        }

        case NodeType.EDGE: {
            const en = node as EdgeNodeModel;
            return {
                ...idField,
                node_name: en.node_name,
                graph: graphId,
                metadata: meta,
            };
        }

        default:
            return null;
    }
}

function buildSchedulePayload(node: ScheduleTriggerNodeModel): Record<string, unknown> {
    const d = node.data;
    if (d.runMode === 'once') {
        return {
            run_mode: 'once',
            start_date_time: d.startDateTime,
            interval: null,
            end: { type: 'never', date_time: null, max_runs: null },
            timezone: d.timezone,
        };
    }
    const unitAllowsWeekdays = d.intervalUnit === 'days' || d.intervalUnit === 'weeks';
    const interval = { every: d.intervalEvery, unit: d.intervalUnit, weekdays: unitAllowsWeekdays ? d.weekdays : [] };
    let end: Record<string, unknown>;
    if (d.endType === 'on_date') {
        end = { type: 'on_date', date_time: d.endDateTime, max_runs: null };
    } else if (d.endType === 'after_n_runs') {
        end = { type: 'after_n_runs', date_time: null, max_runs: d.maxRuns };
    } else {
        end = { type: 'never', date_time: null, max_runs: null };
    }
    return { run_mode: 'repeat', start_date_time: d.startDateTime, interval, end, timezone: d.timezone };
}

function buildDecisionTableBackendPayload(
    node: DecisionTableNodeModel,
    graphId: number,
    allNodes: NodeModel[]
): Record<string, unknown> {
    const idField = node.backendId != null ? { id: node.backendId } : { temp_id: node.id };
    const tableData = node.data.table;
    const conditionGroups = tableData.condition_groups
        .filter((g) => g.valid !== false)
        .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER))
        .map((group, index) => {
            const nextNode = allNodes.find((n) => n.id === group.next_node);
            const nextBackendId = nextNode?.backendId ?? null;
            const nextTempId = !nextBackendId && group.next_node ? group.next_node : undefined;
            return {
                group_name: group.group_name,
                group_type: group.group_type,
                expression: group.expression,
                conditions: group.conditions.map((c) => ({ condition_name: c.condition_name, condition: c.condition })),
                manipulation: group.manipulation,
                next_node_id: nextBackendId,
                ...(nextTempId ? { next_node_temp_id: nextTempId } : {}),
                order: typeof group.order === 'number' ? group.order : index + 1,
            };
        });
    const defaultNext = allNodes.find((n) => n.id === tableData.default_next_node);
    const defaultNextBackendId = defaultNext?.backendId ?? null;
    const errorNext = allNodes.find((n) => n.id === tableData.next_error_node);
    const errorNextBackendId = errorNext?.backendId ?? null;
    return {
        ...idField,
        graph: graphId,
        node_name: node.node_name,
        condition_groups: conditionGroups,
        default_next_node_id: defaultNextBackendId,
        ...(!defaultNextBackendId && tableData.default_next_node
            ? { default_next_node_temp_id: tableData.default_next_node }
            : {}),
        next_error_node_id: errorNextBackendId,
        ...(!errorNextBackendId && tableData.next_error_node
            ? { next_error_node_temp_id: tableData.next_error_node }
            : {}),
        metadata: toNodeMetadata(node),
    };
}

export function connectionToWsPayload(
    conn: ConnectionModel,
    sourceNode: NodeModel,
    targetNode: NodeModel,
    graphId: number
): Record<string, unknown> {
    const connId = conn.data?.id != null ? { id: conn.data.id } : { temp_id: conn.id };
    const startRef =
        sourceNode.backendId != null ? { start_node_id: sourceNode.backendId } : { start_temp_id: sourceNode.id };
    const endRef =
        targetNode.backendId != null ? { end_node_id: targetNode.backendId } : { end_temp_id: targetNode.id };
    const waypoints = conn.waypoints ?? [];
    return { ...connId, graph: graphId, ...startRef, ...endRef, waypoints, metadata: { waypoints } };
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
    public readonly currentUserId = computed(() => this.profileService.currentUserSignal()?.id ?? null);

    public graphFilesChanged$ = new Subject<GraphFilesChangedMessage>();
    public graphSaved$ = new Subject<GraphSavedMessage>();
    public saveFailed$ = new Subject<SaveFailedMessage>();
    public graphState$ = new Subject<GraphStateMessage>();
    public nodeCreated$ = new Subject<NodeCreatedMessage>();
    public nodeUpdated$ = new Subject<NodeUpdatedMessage>();
    public opRejected$ = new Subject<OpRejectedMessage>();
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
    private readonly waypointPipe$ = new Subject<{
        connection_id: number | string;
        waypoints: IPoint[];
        listKey: string;
    }>();
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
                            new Map(Object.entries(fields) as [string, EditorInfo][]),
                        ])
                    )
                );
                break;
            case 'graph_state':
                this.graphState$.next(message);
                break;
            case 'graph_saved':
                this.updateEditorInfo(message.saved_by);
                this.graphSaved$.next(message);
                break;
            case 'graph_files_changed':
                this.graphFilesChanged$.next(message);
                break;
            case 'save_failed':
                this.saveFailed$.next(message);
                break;
            case 'node_created':
                this.nodeCreated$.next(message);
                break;
            case 'node_updated':
                this.nodeUpdated$.next(message);
                break;
            case 'op_rejected':
                this.opRejected$.next(message);
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
            case 'presence_state_updated':
                this.updateEditorInfo(message.editor);
                break;
            case 'error':
                console.error(`[WS] Server error [${message.code}]: ${message.message}`);
                break;
        }
    }

    private updateEditorInfo(editor: EditorInfo): void {
        this.editors.update((list) => {
            const index = list.findIndex((e) => e.user_id === editor.user_id);
            if (index === -1) return list;
            const updated = [...list];
            updated[index] = editor;
            return updated;
        });
    }

    public sendNodeCreated(
        node: NodeModel,
        graphId: number,
        allNodes: NodeModel[] = [],
        connections: ConnectionModel[] = []
    ): void {
        const list_key = nodeTypeToListKey(node.type);
        if (!list_key) return;
        const payload = buildNodeBackendPayload(node, graphId, allNodes, connections);
        if (!payload) return;
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'node_created', node: payload, list_key, editor });
    }

    public sendNodeUpdated(
        node: NodeModel,
        graphId: number,
        allNodes: NodeModel[] = [],
        connections: ConnectionModel[] = [],
        prevNode: NodeModel | null = null
    ): void {
        const list_key = nodeTypeToListKey(node.type);
        if (!list_key) return;
        const payload = buildNodeBackendPayload(node, graphId, allNodes, connections);
        if (!payload) return;
        const editor = this.buildEditorInfo();
        if (!editor) return;

        if (prevNode) {
            const prevPayload = buildNodeBackendPayload(prevNode, graphId, allNodes, connections);
            if (prevPayload) {
                const { node: partial, changed_fields } = buildPartialNodePayload(prevPayload, payload);
                if (changed_fields.length === 0) return;
                this.sendRaw({
                    type: 'node_updated',
                    node: partial,
                    list_key,
                    changed_fields,
                    op_id: crypto.randomUUID(),
                    editor,
                });
                return;
            }
        }

        this.sendRaw({ type: 'node_updated', node: payload, list_key, editor });
    }

    public sendNodePositionDuringDrag(
        node: NodeModel,
        graphId: number,
        allNodes: NodeModel[] = [],
        connections: ConnectionModel[] = []
    ): void {
        const now = Date.now();
        if (now - this.lastNodeDragSendAt < 150) return;
        this.lastNodeDragSendAt = now;
        const list_key = nodeTypeToListKey(node.type);
        if (!list_key) return;
        const payload = buildNodeBackendPayload(node, graphId, allNodes, connections);
        if (!payload) return;
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'node_updated', node: payload, list_key, editor });
    }

    public sendNodesDeleted(refs: EntryDeleteRef[]): void {
        const editor = this.buildEditorInfo();
        if (editor) this.sendRaw({ type: 'nodes_deleted', refs, editor });
    }

    public sendConnectionCreated(
        conn: ConnectionModel,
        listKey: string,
        sourceNode: NodeModel,
        targetNode: NodeModel,
        graphId: number
    ): void {
        const editor = this.buildEditorInfo();
        if (editor)
            this.sendRaw({
                type: 'connection_created',
                connection: connectionToWsPayload(conn, sourceNode, targetNode, graphId),
                list_key: listKey,
                editor,
            });
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

    public sendConnectionWaypointsUpdated(conn: ConnectionModel, waypoints: IPoint[], listKey: string): void {
        const connection_id: number | string = conn.data?.id ?? conn.id;
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
        if (!editor) return;
        this.lockedNodeFields.update((m) => {
            const next = new Map(m);
            const nodeFields = new Map(next.get(node_id) ?? []);
            nodeFields.set(field, editor);
            next.set(node_id, nodeFields);
            return next;
        });
        this.sendRaw({ type: 'node_locked', node_id, field, editor });
    }

    public sendNodeUnlocked(node_id: string, field: string): void {
        const editor = this.buildEditorInfo();
        if (!editor) return;
        this.lockedNodeFields.update((m) => {
            const next = new Map(m);
            const nodeFields = new Map(next.get(node_id) ?? []);
            nodeFields.delete(field);
            if (nodeFields.size === 0) next.delete(node_id);
            else next.set(node_id, nodeFields);
            return next;
        });
        this.sendRaw({ type: 'node_unlocked', node_id, field, editor });
    }

    private buildEditorInfo(): EditorInfo | null {
        const user = this.profileService.currentUserSignal();
        if (!user) return null;
        return { user_id: user.id, display_name: user.display_name, avatar_url: user.avatar_url };
    }

    private sendRaw(payload: object): void {
        console.log('[WS OUT]', payload);
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
