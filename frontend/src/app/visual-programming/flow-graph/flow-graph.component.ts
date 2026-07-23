import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    effect,
    ElementRef,
    EventEmitter,
    inject,
    Injector,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    output,
    signal,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { IPoint, PointExtensions } from '@foblex/2d';
import {
    EFMarkerType,
    EFResizeHandleType,
    EFZoomDirection,
    F_CONNECTION_BUILDERS,
    FCanvasChangeEvent,
    FCanvasComponent,
    FCreateConnectionEvent,
    FCreateNodeEvent,
    FDragStartedEvent,
    FFlowComponent,
    FFlowModule,
    FReassignConnectionEvent,
    FSelectionChangeEvent,
    FZoomDirective,
    ICurrentSelection,
} from '@foblex/flow';
import { Subject, takeUntil } from 'rxjs';
import {
    EditorInfo,
    EntryDeleteRef,
    GraphCollaborationWsService,
    nodeTypeToListKey,
} from 'src/app/features/flows/services/graph-collaboration.ws.service';

import { ImportExportService, PartialExportRequest } from '../../core/services/import-export.service';
import { ToastService } from '../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../shared/components/app-svg-icon/app-svg-icon.component';
import { DomainDialogComponent } from '../components/domain-dialog/domain-dialog.component';
import { FlowActionPanelComponent } from '../components/flow-action-panel/flow-action-panel.component';
import { FlowBaseNodeComponent } from '../components/flow-base-node/flow-base-node.component';
import { FlowExportImportButtonComponent } from '../components/flow-export-import-button/flow-export-import-button.component';
import { FlowFilesButtonComponent } from '../components/flow-files-button/flow-files-button.component';
import { FlowGraphContextMenuComponent } from '../components/flow-graph-context-menu/flow-graph-context-menu.component';
import { FlowSettingsPanelComponent } from '../components/flow-settings-panel/flow-settings-panel.component';
import { FlowShortcutsButtonComponent } from '../components/flow-shortcuts-button/flow-shortcuts-button.component';
import { CdtExportImportService } from '../components/node-panels/classification-decision-table-node-panel/cdt-export-import.service';
import { NodePanelShellComponent } from '../components/node-panels/node-panel-shell/node-panel-shell.component';
import { NodesSearchComponent } from '../components/nodes-search/nodes-search.component';
import { NoteEditDialogComponent } from '../components/note-edit-dialog/note-edit-dialog.component';
import { ProjectDialogComponent } from '../components/project-dialog/project-dialog.component';
import { MouseTrackerDirective } from '../core/directives/mouse-tracker.directive';
import { ShortcutListenerDirective } from '../core/directives/shortcut-listener.directive';
import { WaypointTooltipDirective } from '../core/directives/waypoint-tooltip.directive';
import { NodeType } from '../core/enums/node-type';
import { computeAutoArrangePositions } from '../core/helpers/auto-arrange.util';
import { getAvatarColor } from '../core/helpers/avatar-colors';
import { BackwardArcPathBuilder, computeBackwardArcPoints } from '../core/helpers/backward-arc.path-builder';
import { getMinimapClassForNode } from '../core/helpers/get-minimap-class.util';
import { defineSourceTargetPair, isBackwardConnection, isConnectionValid } from '../core/helpers/helpers';
import {
    findNearestFreePosition,
    getCollisionBounds,
    GRID_CELL_SIZE,
    resolveOverlapsForNode,
    snapPointToGrid,
} from '../core/helpers/node-placement.utils';
import { normalizeTableNodeSize } from '../core/helpers/node-size.util';
import {
    computeSegmentAvoidanceWaypoints,
    getConnectionIntersectingNodes,
    getPortPosition,
    normalizeConnectionWaypoints,
} from '../core/helpers/segment-avoidance.helper';
import { ConnectionModel } from '../core/models/connection.model';
import { FlowModel } from '../core/models/flow.model';
import { GraphNoteModel, NodeModel, ProjectNodeModel, StartNodeModel } from '../core/models/node.model';
import { CreateNodeRequest } from '../core/models/node-creation.types';
import { CustomPortId } from '../core/models/port.model';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { FlowSettingsService } from '../services/flow-settings.service';
import { NodeFactoryService } from '../services/node-factory.service';
import { SidePanelService } from '../services/side-panel.service';
import { ConnectionChange, NodeChange, UndoEntry, UndoRedoService } from '../services/undo-redo.service';
import { createFlowConnection } from '../utils/connection.factory';
import { diffFlowModels, FlowDiffResult } from '../utils/diff-flow-models.util';
import { normalizeFlowPorts } from '../utils/load';
import { CursorState, GraphLiveCursorsComponent } from './graph-live-cursors/graph-live-cursors.component';

function waypointsEqual(a: IPoint[], b: IPoint[]): boolean {
    if (a.length !== b.length) return false;
    return a.every((p, i) => p.x === b[i].x && p.y === b[i].y);
}

@Component({
    selector: 'app-flow-graph',
    templateUrl: './flow-graph.component.html',
    styleUrls: ['../styles/_variables.scss', './flow-graph.component.scss'],
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        {
            provide: F_CONNECTION_BUILDERS,
            useFactory: (flowService: FlowService) => ({
                'backward-arc': new BackwardArcPathBuilder(() => flowService.nodes()),
            }),
            deps: [FlowService],
        },
    ],
    imports: [
        FFlowModule,
        FZoomDirective,
        FormsModule,
        FlowBaseNodeComponent,
        ShortcutListenerDirective,
        MouseTrackerDirective,
        FlowGraphContextMenuComponent,
        FlowActionPanelComponent,
        NodesSearchComponent,
        NodePanelShellComponent,
        FlowShortcutsButtonComponent,
        AppSvgIconComponent,
        WaypointTooltipDirective,
        FlowExportImportButtonComponent,
        FlowFilesButtonComponent,
        GraphLiveCursorsComponent,
        MatTooltipModule,
    ],
})
export class FlowGraphComponent implements OnInit, OnChanges, OnDestroy {
    @Input() flowState!: FlowModel;
    @Input() currentFlowId: number | null = null;
    @Input() flowName: string = '';
    @Input() initialNodeId: string | null = null;
    @Input() hasUnsavedChanges: boolean = false;
    /** @deprecated set only by the deprecated manual REST save path; no bindings remain. */
    @Input() isSaving: boolean = false;

    /** @deprecated emitted only by the deprecated emitSave(); no bindings remain. */
    @Output() save = new EventEmitter<FlowModel>();
    @Output() requestReload = new EventEmitter<void>();
    readonly openShortcuts = output<DOMRect>();
    readonly importComplete = output<void>();

    @ViewChild(FFlowComponent, { static: false })
    private fFlowComponent!: FFlowComponent;

    @ViewChild(FCanvasComponent, { static: true })
    private fCanvasComponent!: FCanvasComponent;

    @ViewChild(FZoomDirective, { static: true })
    private fZoomDirective!: FZoomDirective;

    @ViewChild('nodePanelShell', { static: false })
    private nodePanelShell?: NodePanelShellComponent;

    @ViewChild('arrangeBtnRef') private arrangeBtnRef?: ElementRef<HTMLButtonElement>;

    readonly GRID_CELL_SIZE = GRID_CELL_SIZE;
    protected readonly getMinimapClassForNode = getMinimapClassForNode;
    protected readonly eMarkerType = EFMarkerType;
    protected readonly CONNECTION_DELETE_BUTTON_POSITION = 0.56;
    protected readonly eResizeHandleType = EFResizeHandleType;
    protected readonly NodeType = NodeType;

    protected mouseCursorPosition: IPoint = { x: 0, y: 0 };
    protected contextMenuPosition = signal<IPoint>({ x: 0, y: 0 });
    protected isLoaded = signal(false);
    private arrangeAnimationId: number | null = null;
    private _arrangingLock = false;
    protected showContextMenu = signal(false);
    protected readonly hasUnarrangedChanges = signal(true);
    protected readonly isArranging = signal<boolean>(false);
    protected readonly flowSettings = inject(FlowSettingsService);
    public smartRoutingEnabled = signal<boolean>(false);

    private _dragStartClientX: number | null = null;
    private _dragStartClientY: number | null = null;
    private _dragEndClientX: number | null = null;
    private _dragEndClientY: number | null = null;
    private _isReselecting = false;

    public multiSelectActive = signal<boolean>(false);
    private selectedNodeIds = signal<string[]>([]);
    public selectedNodeCount = computed(() => {
        const nodes = this.flowService.nodes();
        return this.selectedNodeIds().filter((id) => {
            const t = nodes.find((n) => n.id === id)?.type;
            return t !== NodeType.START && t !== NodeType.END;
        }).length;
    });
    public allSelectedAreCdt = computed(() => {
        const ids = this.selectedNodeIds();
        if (ids.length === 0) return false;
        const nodes = this.flowService.nodes();
        return ids.every((id) => nodes.find((n) => n.id === id)?.type === NodeType.CLASSIFICATION_TABLE);
    });

    readonly multiSelectTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        this.multiSelectActive() || (event instanceof MouseEvent && event.shiftKey);

    readonly selectionAreaTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        this.multiSelectActive() || (event instanceof MouseEvent && event.shiftKey);

    readonly canvasMoveTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        !this.multiSelectActive() && !(event instanceof MouseEvent && event.shiftKey);

    protected readonly nodeColorMap = computed<Map<string, string>>(() => {
        const map = new Map<string, string>();
        for (const node of this.flowService.nodes()) {
            map.set(node.id, node.color);
        }
        return map;
    });

    protected readonly backwardConnectionIds = computed<Set<string>>(() => {
        const nodes = this.flowService.nodes();
        const connections = this.flowService.visibleConnections();
        const ids = new Set<string>();

        for (const conn of connections) {
            if (isBackwardConnection(conn, nodes)) {
                ids.add(conn.id);
            }
        }

        return ids;
    });

    protected readonly sortedConnections = computed(() => {
        const backwardIds = this.backwardConnectionIds();
        const hiddenIds = this.hiddenConnectionIds();

        const connections = [...this.flowService.visibleConnections()].filter(
            (connection) => !hiddenIds.has(connection.id)
        );

        return connections.sort((a, b) => {
            const aBackward = backwardIds.has(a.id) ? 1 : 0;
            const bBackward = backwardIds.has(b.id) ? 1 : 0;

            return aBackward - bBackward;
        });
    });

    public hoveredNodeId = signal<string | null>(null);

    public getNodeZIndex(node: NodeModel): number {
        if (this.hoveredNodeId() === node.id) return 1000;
        return Math.max(2, 500 - Math.floor(Math.max(0, node.position?.y ?? 0) / 10));
    }

    private fitAfterNextFlowChange = false;
    private _preImportBackendIds: Set<number> | null = null;
    private _importPositionSnapshot: Map<number, { x: number; y: number }> | null = null;

    private readonly destroy$ = new Subject<void>();
    private readonly userAdjustedConnectionIds = new Set<string>();
    private readonly previousBackwardConnectionIds = new Set<string>();
    private draggedNodeIds = new Set<string>();
    private draggingElements = new Set<string>();
    private isDragging = false;
    private dragStartCanvasPos: IPoint | null = null;
    private readonly dragStartPositions = new Map<string, IPoint>();
    protected readonly connectionRenderVersions = signal<Record<string, number>>({});
    private readonly hiddenConnectionIds = signal<Set<string>>(new Set<string>());

    protected readonly flowService = inject(FlowService);
    protected readonly sidePanelService = inject(SidePanelService);
    private readonly undoRedoService = inject(UndoRedoService);
    private readonly clipboardService = inject(ClipboardService);
    private readonly nodeFactory = inject(NodeFactoryService);
    private readonly cd = inject(ChangeDetectorRef);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly importExportService = inject(ImportExportService);
    private readonly cdtExportImportService = inject(CdtExportImportService);
    private readonly injector = inject(Injector);
    private readonly wsService = inject(GraphCollaborationWsService);
    public readonly remoteCursors = signal<Map<number, CursorState>>(new Map());
    private readonly cursorTimeouts = new Map<number, ReturnType<typeof setTimeout>>();
    private readonly canvasTransform = signal<{ x: number; y: number; scale: number }>({ x: 0, y: 0, scale: 1 });
    public readonly remoteSelections = signal<Map<number, string[]>>(new Map());
    protected readonly screenCursors = computed(() => {
        const t = this.canvasTransform();
        const result = new Map<number, CursorState>();
        for (const [userId, cursor] of this.remoteCursors()) {
            result.set(userId, {
                ...cursor,
                x: cursor.x * t.scale + t.x,
                y: cursor.y * t.scale + t.y,
            });
        }
        return result;
    });
    private readonly pendingUndoOps = new Map<
        string,
        { revert: NodeModel; entry: UndoEntry; direction: 'undo' | 'redo' }
    >();

    protected readonly remoteSelectionColors = computed<Map<string, string>>(() => {
        const result = new Map<string, string>();
        for (const [userId, nodeIds] of this.remoteSelections()) {
            const color = getAvatarColor(userId);
            for (const nodeId of nodeIds) {
                result.set(nodeId, color);
            }
        }
        return result;
    });

    protected readonly nodeLockedMap = computed<Map<string, EditorInfo>>(() => {
        const myId = this.wsService.currentUserId();
        const result = new Map<string, EditorInfo>();
        for (const [nodeId, fields] of this.wsService.lockedNodeFields()) {
            for (const editor of fields.values()) {
                if (editor.user_id !== myId) {
                    result.set(nodeId, editor);
                    break;
                }
            }
        }
        return result;
    });

    private lastSeenFullSaveRequest = 0;

    constructor() {
        effect(() => {
            const request = this.sidePanelService.fullSaveRequest();
            if (request.seq > this.lastSeenFullSaveRequest) {
                this.lastSeenFullSaveRequest = request.seq;
                if (request.before) {
                    this.broadcastFlowDiff(diffFlowModels(request.before, this.flowService.getFlowState()));
                }
            }
        });
    }

    public ngOnInit(): void {
        this.applyIncomingFlowState(this.flowState);
        if (this.initialNodeId) {
            this.openNodePanel(this.initialNodeId);
        }

        this.wsService.cursorMoved$.pipe(takeUntil(this.destroy$)).subscribe((msg) => {
            const userId = msg.editor.user_id;

            const prev = this.cursorTimeouts.get(userId);
            if (prev) clearTimeout(prev);

            this.remoteCursors.update((m) => {
                const next = new Map(m);
                next.set(userId, { x: msg.x, y: msg.y, editor: msg.editor, fading: false });
                return next;
            });

            const fadeTimeout = setTimeout(() => {
                this.remoteCursors.update((m) => {
                    const next = new Map(m);
                    const cursor = next.get(userId);
                    if (cursor) next.set(userId, { ...cursor, fading: true });
                    return next;
                });
                setTimeout(() => {
                    this.remoteCursors.update((m) => {
                        const next = new Map(m);
                        next.delete(userId);
                        return next;
                    });
                    this.cursorTimeouts.delete(userId);
                }, 400);
            }, 3000);

            this.cursorTimeouts.set(userId, fadeTimeout);
        });

        this.wsService.selectionChanged$.pipe(takeUntil(this.destroy$)).subscribe((msg) => {
            this.remoteSelections.update((m) => {
                const next = new Map(m);
                if (msg.node_ids.length === 0) {
                    next.delete(msg.editor.user_id);
                } else {
                    next.set(msg.editor.user_id, msg.node_ids);
                }
                return next;
            });
        });

        this.wsService.opRejected$.pipe(takeUntil(this.destroy$)).subscribe((msg) => {
            if (msg.reason !== 'precondition_failed' || !msg.op_id) return;
            const pending = this.pendingUndoOps.get(msg.op_id);
            if (!pending) return;
            this.pendingUndoOps.delete(msg.op_id);
            this.flowService.updateNode(pending.revert);
            if (pending.direction === 'undo') {
                this.undoRedoService.restoreUndo(pending.entry);
            } else {
                this.undoRedoService.restoreRedo(pending.entry);
            }
            this.toastService.warning('Не вдалося відкотити — поле змінив інший користувач', 5000, 'bottom-right');
        });

        this.wsService.nodeUnlocked$.pipe(takeUntil(this.destroy$)).subscribe((msg) => {
            if (msg.editor.user_id !== this.wsService.currentUserId()) return;
            const selectedNode = this.sidePanelService.selectedNode();
            if (!selectedNode || selectedNode.id !== msg.node_id) return;
            this.sidePanelService.triggerAutosave();
        });

        effect(
            () => {
                const editorIds = new Set(this.wsService.editors().map((e) => e.user_id));
                this.remoteSelections.update((m) => {
                    const toDelete = [...m.keys()].filter((uid) => !editorIds.has(uid));
                    if (toDelete.length === 0) return m;
                    const next = new Map(m);
                    toDelete.forEach((uid) => next.delete(uid));
                    return next;
                });
            },
            { injector: this.injector }
        );
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['flowState'] && !changes['flowState'].firstChange) {
            const stateToApply = this._preImportBackendIds
                ? this._shiftImportedNodes(this.flowState, this._preImportBackendIds)
                : this.flowState;
            this._preImportBackendIds = null;
            this.applyIncomingFlowState(stateToApply);
            if (this.fitAfterNextFlowChange) {
                this.fitAfterNextFlowChange = false;
                setTimeout(() => {
                    this.fCanvasComponent.fitToScreen({ x: 200, y: 100 }, false);
                }, 0);
            }
        }
        if (changes['initialNodeId'] && changes['initialNodeId'].currentValue) {
            this.openNodePanel(changes['initialNodeId'].currentValue);
        }
    }

    public ngOnDestroy(): void {
        if (this.arrangeAnimationId !== null) {
            cancelAnimationFrame(this.arrangeAnimationId);
        }
        this.cursorTimeouts.forEach((t) => clearTimeout(t));
        this.cursorTimeouts.clear();

        this.destroy$.next();
        this.destroy$.complete();
    }

    public onInitialized(): void {
        this.isLoaded.set(true);
        setTimeout(() => {
            this.rerouteSegmentConnections();
            this.fCanvasComponent.fitToScreen({ x: 200, y: 100 }, false);
            if (this.flowService.nodes().length === 1) {
                this.fCanvasComponent.setScale(0.1);
            }
            this.cd.detectChanges();
        }, 0);
    }

    public onReassignConnection(event: FReassignConnectionEvent): void {
        this.hasUnarrangedChanges.set(true);
        if (!event.newTargetId && !event.newSourceId) {
            console.warn('No new target or source provided for reassignment');
            return;
        }

        this.recordAfterChange();

        const existingConnection = this.flowService.connections().find((conn) => conn.id === event.connectionId);

        if (!existingConnection) {
            console.warn('Connection not found for reassignment:', event.connectionId);
            return;
        }

        const newSourcePortId = event.newSourceId || existingConnection.sourcePortId;
        const newTargetPortId = event.newTargetId || existingConnection.targetPortId;

        if (!isConnectionValid(newSourcePortId as CustomPortId, newTargetPortId as CustomPortId)) {
            console.warn('New connection is invalid. Reassignment aborted.');
            this.toastService.warning('Cannot reassign connection: Invalid port combination', 5000, 'bottom-right');
            return;
        }

        const newSourceNodeId = newSourcePortId.split('_')[0];
        const newTargetNodeId = newTargetPortId.split('_')[0];

        const updatedConnection = createFlowConnection(
            newSourceNodeId,
            newTargetNodeId,
            newSourcePortId as CustomPortId,
            newTargetPortId as CustomPortId
        );

        const oldSourceIsDecisionRouting = this.isDecisionRoutingSource(
            this.flowService.nodes().find((n) => n.id === existingConnection.sourceNodeId)?.type
        );
        const deleteRef = this.buildConnectionDeleteRef(existingConnection);
        this.flowService.removeConnection(event.connectionId);
        if (!oldSourceIsDecisionRouting) {
            this.wsService.sendConnectionDeleted(deleteRef);
        }
        this.flowService.addConnection(updatedConnection);
        if (oldSourceIsDecisionRouting) {
            // Old table source lost this route — broadcast its updated routing.
            this.broadcastDecisionRoutingUpdate(existingConnection.sourceNodeId);
        }
        const reassignSourceNode = this.flowService.nodes().find((n) => n.id === newSourceNodeId);
        const reassignTargetNode = this.flowService.nodes().find((n) => n.id === newTargetNodeId);
        if (reassignSourceNode && reassignTargetNode) {
            if (this.isDecisionRoutingSource(reassignSourceNode.type)) {
                this.broadcastDecisionRoutingUpdate(reassignSourceNode.id);
            } else {
                this.wsService.sendConnectionCreated(
                    updatedConnection,
                    this.getConnectionListKey(updatedConnection),
                    reassignSourceNode,
                    reassignTargetNode,
                    this.currentFlowId!
                );
            }
        }

        this.toastService.success('Connection reassigned successfully', 3000, 'bottom-right');
    }

    public onConnectionAdded(event: FCreateConnectionEvent): void {
        this.hasUnarrangedChanges.set(true);
        this.recordAfterChange();

        const { fOutputId, fInputId } = event;

        if (!fInputId) {
            console.warn('Connection event received without an input ID:', event);
            return;
        }

        if (!isConnectionValid(fOutputId as CustomPortId, fInputId as CustomPortId)) {
            console.warn('Connection is invalid and will not be added:', fOutputId, fInputId);
            return;
        }

        const pair = defineSourceTargetPair(fOutputId as CustomPortId, fInputId as CustomPortId);
        if (!pair) {
            console.warn('Failed to define source-target pair for ports:', fOutputId, fInputId);
            return;
        }

        const currentConnections = this.flowService.connections();

        const isDuplicate = currentConnections.some(
            (conn) => conn.sourcePortId === pair.sourcePortId && conn.targetPortId === pair.targetPortId
        );
        if (isDuplicate) {
            console.warn('Duplicate connection detected, ignoring:', `${pair.sourcePortId}+${pair.targetPortId}`);
            return;
        }

        const sourceNodeId = pair.sourcePortId.split('_')[0];
        const targetNodeId = pair.targetPortId.split('_')[0];

        const newConnection = createFlowConnection(
            sourceNodeId,
            targetNodeId,
            pair.sourcePortId as CustomPortId,
            pair.targetPortId as CustomPortId
        );

        this.flowService.addConnection(newConnection);
        const connNodes = this.flowService.nodes();
        const connSourceNode = connNodes.find((n) => n.id === sourceNodeId);
        const connTargetNode = connNodes.find((n) => n.id === targetNodeId);
        if (connSourceNode && connTargetNode) {
            if (this.isDecisionRoutingSource(connSourceNode.type)) {
                // Decision/classification table routing is persisted inside the
                // node entity, not as an edge — broadcast the node update
                // instead of a connection_created.
                this.broadcastDecisionRoutingUpdate(connSourceNode.id);
            } else {
                this.wsService.sendConnectionCreated(
                    newConnection,
                    this.getConnectionListKey(newConnection),
                    connSourceNode,
                    connTargetNode,
                    this.currentFlowId!
                );
            }
        }

        const nodes = this.flowService.nodes();
        const intersects = getConnectionIntersectingNodes(newConnection, nodes);

        const newConnTargetNode = nodes.find((n) => n.id === newConnection.targetNodeId);
        const newConnTargetPort = newConnTargetNode?.ports?.find((p) => p.id === newConnection.targetPortId);
        const isTableInTarget =
            newConnTargetNode?.type === NodeType.TABLE && newConnTargetPort?.id?.includes('table-in');

        if (intersects.length > 0 || isTableInTarget) {
            const avoidWaypoints = computeSegmentAvoidanceWaypoints(newConnection, nodes);
            if (avoidWaypoints) {
                const normalizedWaypoints = this.normalizeWaypointsForConnection(newConnection, avoidWaypoints);
                this.flowService.updateConnectionWaypoints(newConnection.id, normalizedWaypoints);
                this.bumpConnectionRenderVersion(newConnection.id);
            }
        }
    }

    public onCopy(): void {
        if (this.isDialogOpen()) {
            return;
        }

        const selections: ICurrentSelection = this.fFlowComponent.getSelection();
        this.clipboardService.copy(selections);
    }

    public onPaste(): void {
        this.hasUnarrangedChanges.set(true);
        if (this.isEditingLocked()) {
            return;
        }

        const pastePosition = this.mouseCursorPosition
            ? snapPointToGrid(this.toFlowPosition(this.mouseCursorPosition))
            : { x: 0, y: 0 };

        this.recordAfterChange();
        const { newNodes, newConnections } = this.clipboardService.paste(pastePosition);
        const placedNodes: NodeModel[] = [];
        const existingBeforePaste = this.flowService.nodes().filter((n) => !newNodes.some((p) => p.id === n.id));

        for (const node of newNodes) {
            const safePosition = findNearestFreePosition(snapPointToGrid(node.position), getCollisionBounds(node), [
                ...existingBeforePaste,
                ...placedNodes,
            ]);

            const updatedNode = { ...node, position: safePosition };
            this.flowService.updateNode(updatedNode);
            this.wsService.sendNodeCreated(
                updatedNode,
                this.currentFlowId!,
                this.flowState.nodes,
                this.flowService.connections()
            );
            placedNodes.push(updatedNode);
        }

        const newNodeIds = newNodes.map((node) => node.id);
        const newConnectionIds = newConnections.map((conn) => conn.id);

        setTimeout(() => {
            this.fFlowComponent.select(newNodeIds, newConnectionIds);
        }, 0);
    }

    public onUndo(): void {
        const entry = this.undoRedoService.popUndo();
        if (entry) this.applyUndoEntry(entry, 'undo');
    }

    public onRedo(): void {
        const entry = this.undoRedoService.popRedo();
        if (entry) this.applyUndoEntry(entry, 'redo');
    }

    public onDelete(): void {
        this.hasUnarrangedChanges.set(true);
        if (this.isEditingLocked()) {
            return;
        }

        const selections: ICurrentSelection = this.fFlowComponent.getSelection();
        this.deleteSelections(selections);
    }

    public onDeleteNode(node: NodeModel): void {
        this.hasUnarrangedChanges.set(true);
        this.deleteSelections({
            fNodeIds: [node.id],
            fGroupIds: [],
            fConnectionIds: [],
        });
    }

    public onDeleteConnection(event: MouseEvent, connectionId: string): void {
        this.hasUnarrangedChanges.set(true);
        event.preventDefault();
        event.stopPropagation();

        if (this.isDialogOpen()) {
            return;
        }

        this.deleteSelections({
            fNodeIds: [],
            fGroupIds: [],
            fConnectionIds: [connectionId],
        });
    }

    protected onWaypointsChanged(connectionId: string, waypoints: IPoint[]): void {
        const connection = this.flowService.connections().find((c) => c.id === connectionId);
        if (!connection) return;

        const existingCount = connection.waypoints?.length ?? 0;
        if (waypoints.length > existingCount) {
            this.userAdjustedConnectionIds.add(connectionId);
            this.flowService.updateConnectionWaypoints(connectionId, waypoints, true);
            this.wsService.sendConnectionWaypointsUpdated(connection, waypoints, this.getConnectionListKey(connection));
            return;
        }

        const normalizedWaypoints = this.normalizeWaypointsForConnection(connection, waypoints);

        if (normalizedWaypoints.length > 0) {
            this.userAdjustedConnectionIds.add(connectionId);
        } else {
            this.userAdjustedConnectionIds.delete(connectionId);
        }

        const isSameElements =
            normalizedWaypoints.length === waypoints.length && normalizedWaypoints.every((p, i) => p === waypoints[i]);

        this.flowService.updateConnectionWaypoints(
            connectionId,
            isSameElements ? waypoints : normalizedWaypoints,
            normalizedWaypoints.length > 0
        );
        this.wsService.sendConnectionWaypointsUpdated(
            connection,
            isSameElements ? waypoints : normalizedWaypoints,
            this.getConnectionListKey(connection)
        );
    }

    public onNodeDroppedFromPanel(event: FCreateNodeEvent): void {
        this.hasUnarrangedChanges.set(true);
        if (!event.data || typeof event.data !== 'object') {
            return;
        }

        const normalizedNode = this.ensureNodeSize(event.data as NodeModel);

        const updatedNode: NodeModel = {
            ...normalizedNode,
            position: this.findNearestFreePosition(
                {
                    x: this.snapToGrid(event.rect.x),
                    y: this.snapToGrid(event.rect.y),
                },
                this.getCollisionBounds(normalizedNode),
                this.flowService.nodes()
            ),
        };
        this.flowService.updateNode(updatedNode);
        this.wsService.sendNodeCreated(
            updatedNode,
            this.currentFlowId!,
            this.flowState.nodes,
            this.flowService.connections()
        );
    }

    public onContextMenu(event: MouseEvent): void {
        event.preventDefault();
        this.contextMenuPosition.set({ x: event.clientX, y: event.clientY });
        this.showContextMenu.set(true);
    }

    public onCloseContextMenu(): void {
        this.showContextMenu.set(false);
    }

    public onAddNodeFromContextMenu(event: CreateNodeRequest): void {
        this.hasUnarrangedChanges.set(true);
        this.recordAfterChange();
        this.showContextMenu.set(false);

        if (event.type === NodeType.END && this.flowService.hasEndNode()) {
            this.toastService.warning('Only one End node is allowed', 4000, 'bottom-right');
            return;
        }

        if (this.isDialogOpen()) {
            return;
        }

        const position = this.fFlowComponent.getPositionInFlow(
            PointExtensions.initialize(this.contextMenuPosition().x, this.contextMenuPosition().y)
        );
        const newNode = this.nodeFactory.createNode(event.type, { ...event.overrides, position });
        this.flowService.addNode(newNode);
        this.wsService.sendNodeCreated(
            newNode,
            this.currentFlowId!,
            this.flowState.nodes,
            this.flowService.connections()
        );
    }

    public onOpenNodePanel(node: NodeModel): void {
        if (this.multiSelectActive()) {
            const current = this.fFlowComponent.getSelection();
            const alreadySelected = current.fNodeIds.includes(node.id);
            const newNodeIds = alreadySelected
                ? current.fNodeIds.filter((id) => id !== node.id)
                : [...current.fNodeIds, node.id];
            this.selectedNodeIds.set(newNodeIds);
            this.fFlowComponent.select(newNodeIds, current.fConnectionIds);
            return;
        }

        if (this.sidePanelService.selectedNodeId() === node.id) {
            return;
        }

        if (node.type === NodeType.NOTE) {
            const noteNode = node as GraphNoteModel;

            const dialogRef = this.dialog.open(NoteEditDialogComponent, {
                data: { node: noteNode },
                disableClose: true,
            });

            dialogRef.closed.subscribe((result: unknown) => {
                if (
                    result !== null &&
                    typeof result === 'object' &&
                    'content' in result &&
                    typeof (result as { content?: unknown }).content !== 'undefined'
                ) {
                    const content = (result as { content?: unknown }).content;
                    if (typeof content !== 'string') return;

                    const updatedNode: GraphNoteModel = {
                        ...noteNode,
                        data: {
                            ...noteNode.data,
                            content,
                        },
                    };

                    this.flowService.updateNode(updatedNode);
                    this.wsService.sendNodeUpdated(
                        updatedNode,
                        this.currentFlowId!,
                        this.flowState.nodes,
                        this.flowService.connections()
                    );
                    this.cd.detectChanges();
                }
            });
        } else if (node.type === NodeType.START) {
            const startNode = node as StartNodeModel;
            const startNodeInitialState = startNode.data?.initialState || {};

            const dialogRef = this.dialog.open(DomainDialogComponent, {
                disableClose: true,
                width: '1000px',
                height: '800px',
                maxWidth: '90vw',
                maxHeight: '90vh',
                panelClass: 'domain-dialog-panel',
                backdropClass: 'domain-dialog-backdrop',
                data: {
                    initialData: startNodeInitialState,
                },
            });

            dialogRef.closed.subscribe((result: unknown) => {
                if (result !== null && typeof result === 'object' && result !== undefined) {
                    this.updateStartNodeInitialState(result as Record<string, unknown>);
                }
            });
        } else {
            void this.sidePanelService.trySelectNode(node);
        }
    }

    public onNodePanelSaved(updatedNode: NodeModel): void {
        this.recordAfterChange();
        const normalizedNode = normalizeTableNodeSize(updatedNode);
        const prev = this.flowService.nodes().find((n) => n.id === normalizedNode.id) ?? null;
        this.flowService.updateNode(normalizedNode);
        this.wsService.sendNodeUpdated(
            normalizedNode,
            this.currentFlowId!,
            this.flowState.nodes,
            this.flowService.connections(),
            prev
        );
        const movedNodeIds = this.resolveTableOverlaps(normalizedNode);
        this.sidePanelService.clearSelection();

        setTimeout(() => {
            this.rerouteSegmentConnections();

            const affectedNodeIds = new Set<string>([normalizedNode.id, ...movedNodeIds]);

            for (const conn of this.flowService.connections()) {
                if (affectedNodeIds.has(conn.sourceNodeId) || affectedNodeIds.has(conn.targetNodeId)) {
                    this.bumpConnectionRenderVersion(conn.id);
                }
            }

            this.cd.detectChanges();
        }, 0);
    }

    public onNodePanelAutosaved(updatedNode: NodeModel): void {
        this.recordAfterChange();
        const normalizedNode = normalizeTableNodeSize(updatedNode);
        const prev = this.flowService.nodes().find((n) => n.id === normalizedNode.id) ?? null;
        this.flowService.updateNode(normalizedNode);
        this.wsService.sendNodeUpdated(
            normalizedNode,
            this.currentFlowId!,
            this.flowState.nodes,
            this.flowService.connections(),
            prev
        );
        const movedNodeIds = this.resolveTableOverlaps(normalizedNode);

        setTimeout(() => {
            this.rerouteSegmentConnections();

            const affectedNodeIds = new Set<string>([normalizedNode.id, ...movedNodeIds]);

            for (const conn of this.flowService.connections()) {
                if (affectedNodeIds.has(conn.sourceNodeId) || affectedNodeIds.has(conn.targetNodeId)) {
                    this.bumpConnectionRenderVersion(conn.id);
                }
            }

            this.cd.detectChanges();
        }, 0);
    }

    /** @deprecated Manual save removed in EST-3020 (WS autosave persists everything). Kept for potential rollback; no call sites. */
    public commitSidePanelToFlow(): void {
        const updatedNode = this.nodePanelShell?.captureCurrentNodeState();
        if (updatedNode) {
            this.flowService.updateNode(updatedNode);
        }
    }

    /** @deprecated Manual save removed in EST-3020 (WS autosave persists everything). Kept for potential rollback; no call sites. */
    public emitSave(): void {
        if (this.nodePanelShell?.hasPanelInstance()) {
            const updatedNode = this.nodePanelShell.captureCurrentNodeState();
            if (updatedNode === null) {
                return;
            }
            // Skip the writeback if the captured node was removed from the flow
            // (e.g. during DT→CDT conversion the old panel instance lingers briefly
            //  before the outlet swaps to the newly-selected node's panel).
            if (this.flowService.nodes().some((n) => n.id === updatedNode.id)) {
                this.flowService.updateNode(updatedNode);
            }
        }
        this.save.emit(this.flowService.getFlowState());
    }

    public onNodeSizeChanged(event: { width: number; height: number }, node: NodeModel): void {
        this.recordAfterChange();

        const updatedNode = {
            ...node,
            size: {
                width: event.width,
                height: event.height,
            },
        };

        this.flowService.updateNode(updatedNode);
        this.wsService.sendNodeUpdated(
            updatedNode,
            this.currentFlowId!,
            this.flowState.nodes,
            this.flowService.connections()
        );
    }

    public onDragStarted(event: FDragStartedEvent): void {
        this.isDragging = true;
        this.draggingElements.clear();
        this.dragStartPositions.clear();

        const dragData = event.fData as { fNodeIds?: string[] } | undefined;
        if (dragData?.fNodeIds) {
            dragData.fNodeIds.forEach((id: string) => this.draggingElements.add(id));
        }

        if (this.fFlowComponent) {
            this.dragStartCanvasPos = this.toFlowPosition(this.mouseCursorPosition);
            const nodes = this.flowService.nodes();
            for (const id of this.draggingElements) {
                const node = nodes.find((n) => n.id === id);
                if (node) this.dragStartPositions.set(id, { ...node.position });
            }
        }

        this.recordAfterChange();
    }

    private rerouteSegmentConnections(): void {
        const nodes = this.flowService.nodes();
        const connections = this.flowService.connections();
        const backwardIds = this.backwardConnectionIds();

        for (const conn of connections) {
            const wasBackward = this.previousBackwardConnectionIds.has(conn.id);
            const isBackward = backwardIds.has(conn.id);
            const changedFromBackwardToForward = wasBackward && !isBackward;

            if (isBackward) {
                if (this.userAdjustedConnectionIds.has(conn.id)) continue;

                const bwSource = nodes.find((n) => n.id === conn.sourceNodeId);
                const bwTarget = nodes.find((n) => n.id === conn.targetNodeId);
                if (!bwSource || !bwTarget) continue;

                const bwSourcePort = bwSource.ports?.find((p) => p.id === conn.sourcePortId);
                const bwTargetPort = bwTarget.ports?.find((p) => p.id === conn.targetPortId);

                const bwSourcePt = getPortPosition(bwSource, bwSourcePort);
                const bwTargetPt = getPortPosition(bwTarget, bwTargetPort);

                const arcPts = computeBackwardArcPoints(bwSourcePt, bwTargetPt, undefined, nodes);
                const newWaypoint = {
                    x: (arcPts[1].x + arcPts[4].x) / 2,
                    y: arcPts[2].y,
                };

                const existing = conn.waypoints?.[0];
                const changed =
                    !existing ||
                    Math.abs(existing.y - newWaypoint.y) > 0.5 ||
                    Math.abs(existing.x - newWaypoint.x) > 0.5;

                if (changed) {
                    this.flowService.updateConnectionWaypoints(conn.id, [newWaypoint]);
                    this.bumpConnectionRenderVersion(conn.id);
                }

                continue;
            }

            if (this.userAdjustedConnectionIds.has(conn.id)) continue;

            const MAX_ATTEMPTS = 3;
            let current = this.flowService.connections().find((c) => c.id === conn.id);
            if (!current) continue;

            const currentConnection = current;
            const currentIntersections = getConnectionIntersectingNodes(currentConnection, nodes);

            if (currentIntersections.length === 0) {
                const rerouteTargetNode = nodes.find((n) => n.id === currentConnection.targetNodeId);
                const rerouteTargetPort = rerouteTargetNode?.ports?.find(
                    (p) => p.id === currentConnection.targetPortId
                );
                const isTableInConn =
                    rerouteTargetNode?.type === NodeType.TABLE && rerouteTargetPort?.id?.includes('table-in');

                if (
                    !changedFromBackwardToForward &&
                    !isTableInConn &&
                    (!currentConnection.waypoints || currentConnection.waypoints.length === 0)
                ) {
                    continue;
                }

                const restoreResult = computeSegmentAvoidanceWaypoints(
                    currentConnection,
                    nodes,
                    changedFromBackwardToForward
                        ? undefined
                        : currentConnection.waypoints?.length
                          ? currentConnection.waypoints
                          : undefined
                );

                if (restoreResult !== null) {
                    const normalizedRestore = this.normalizeWaypointsForConnection(currentConnection, restoreResult);

                    if (!waypointsEqual(currentConnection.waypoints ?? [], normalizedRestore)) {
                        this.flowService.updateConnectionWaypoints(currentConnection.id, normalizedRestore);
                        this.bumpConnectionRenderVersion(currentConnection.id);
                    }
                }

                continue;
            }

            for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
                const waypoints = computeSegmentAvoidanceWaypoints(
                    current,
                    nodes,
                    changedFromBackwardToForward ? undefined : current.waypoints
                );

                if (waypoints === null) break;

                const normalizedWaypoints = this.normalizeWaypointsForConnection(current, waypoints);
                if (waypointsEqual(current.waypoints ?? [], normalizedWaypoints)) break;

                this.flowService.updateConnectionWaypoints(current.id, normalizedWaypoints);
                this.bumpConnectionRenderVersion(current.id);
                current = { ...current, waypoints: normalizedWaypoints };
            }
        }

        this.previousBackwardConnectionIds.clear();

        for (const id of backwardIds) {
            this.previousBackwardConnectionIds.add(id);
        }
    }

    public onDragEnded(): void {
        this.dragStartCanvasPos = null;
        this.dragStartPositions.clear();

        const autoAlignedNodeIds = new Set<string>();

        for (const id of this.draggedNodeIds) {
            const currentNodes = this.flowService.nodes();
            const current = currentNodes.find((n) => n.id === id);
            if (!current) continue;

            const otherNodes = currentNodes.filter((n) => n.id !== id);
            const freePos = this.findNearestFreePosition(
                current.position,
                this.getCollisionBounds(current),
                otherNodes
            );

            if (freePos.x !== current.position.x || freePos.y !== current.position.y) {
                this.flowService.updateNode({ ...current, position: freePos });
                this.wsService.sendNodeUpdated(
                    { ...current, position: freePos },
                    this.currentFlowId!,
                    this.flowState.nodes,
                    this.flowService.connections()
                );
                autoAlignedNodeIds.add(id);
            } else {
                this.wsService.sendNodeUpdated(
                    current,
                    this.currentFlowId!,
                    this.flowState.nodes,
                    this.flowService.connections()
                );
            }
        }

        this.draggedNodeIds.clear();

        setTimeout(() => {
            this.isDragging = false;
            this.draggingElements.clear();

            if (autoAlignedNodeIds.size > 0) {
                this.syncAfterAutoAlign(autoAlignedNodeIds);
            } else {
                this.rerouteSegmentConnections();
                this.cd.detectChanges();
                this.fFlowComponent?.redraw();
            }
        }, 100);
    }

    public onNodePositionChanged(newPos: IPoint, node: NodeModel): void {
        this.hasUnarrangedChanges.set(true);
        this.draggedNodeIds.add(node.id);

        if (!this.isDragging || !this.draggingElements.has(node.id)) {
            this.recordAfterChange();
        }

        const updatedNode = {
            ...node,
            position: {
                x: this.snapToGrid(newPos.x),
                y: this.snapToGrid(newPos.y),
            },
        };

        this.flowService.updateNode(updatedNode);
        this.wsService.sendNodePositionDuringDrag(
            updatedNode,
            this.currentFlowId!,
            this.flowState.nodes,
            this.flowService.connections()
        );
    }

    public onZoomInNode(node: NodeModel): void {
        this.fCanvasComponent.centerGroupOrNode(node.id, true);
    }

    public onNodeDoubleClickAndZoom(data: { node: NodeModel; event: MouseEvent }): void {
        const position = {
            x: data.node.position.x,
            y: data.node.position.y,
        };

        this.fCanvasComponent.centerGroupOrNode(data.node.id, false);
        this.fZoomDirective.setZoom(position, 1, EFZoomDirection.ZOOM_IN, true);
    }

    public onCanvasChange(event: FCanvasChangeEvent): void {
        this.canvasTransform.set({ x: event.position.x, y: event.position.y, scale: event.scale });
    }

    public onSmartRoutingToggle(value: boolean): void {
        this.smartRoutingEnabled.set(value);
    }

    protected openSettings(): void {
        this.dialog.open(FlowSettingsPanelComponent, {
            width: '480px',
            maxWidth: '90vw',
        });
    }

    public updateMouseTrackerPosition(event: IPoint): void {
        this.mouseCursorPosition = event;
        if (this.fFlowComponent && this.isLoaded()) {
            const flowPos = this.toFlowPosition(event);
            this.wsService.sendCursorMoved(flowPos.x, flowPos.y);

            if (this.isDragging && this.dragStartCanvasPos && this.draggingElements.size > 0) {
                const delta = { x: flowPos.x - this.dragStartCanvasPos.x, y: flowPos.y - this.dragStartCanvasPos.y };
                const nodes = this.flowService.nodes();
                for (const id of this.draggingElements) {
                    const startPos = this.dragStartPositions.get(id);
                    const node = nodes.find((n) => n.id === id);
                    if (startPos && node) {
                        this.wsService.sendNodePositionDuringDrag(
                            {
                                ...node,
                                position: { x: startPos.x + delta.x, y: startPos.y + delta.y },
                            },
                            this.currentFlowId!,
                            this.flowState.nodes,
                            this.flowService.connections()
                        );
                    }
                }
            }
        }
    }

    public onSelectionChanged(event: FSelectionChangeEvent): void {
        this.wsService.sendSelectionChanged(event.nodeIds);
    }

    public onAutoArrange(): void {
        if (this._arrangingLock) return;
        this._arrangingLock = true;
        this.isArranging.set(true);
        if (this.arrangeBtnRef) {
            this.arrangeBtnRef.nativeElement.disabled = true;
        }

        const nodes = this.flowService.nodes();
        if (nodes.length === 0) {
            this._arrangingLock = false;
            this.isArranging.set(false);
            if (this.arrangeBtnRef) {
                this.arrangeBtnRef.nativeElement.disabled = false;
            }
            return;
        }

        const connections = this.flowService.connections();
        const newPositions = computeAutoArrangePositions(nodes, connections);

        const alreadyArranged = nodes.every((n) => {
            const target = newPositions.get(n.id);
            return !target || (n.position.x === target.x && n.position.y === target.y);
        });
        if (alreadyArranged) {
            this.hasUnarrangedChanges.set(false);
            this._arrangingLock = false;
            this.isArranging.set(false);
            return;
        }

        this.recordAfterChange();

        const startPositions = new Map(nodes.map((n) => [n.id, { ...n.position }]));

        // Pre-identify non-user-adjusted backward connections for per-frame arc updates.
        const backwardIds = this.backwardConnectionIds();
        const backwardConns = connections.filter(
            (c) => backwardIds.has(c.id) && !this.userAdjustedConnectionIds.has(c.id)
        );

        // Clear ALL non-user-adjusted waypoints (including backward) so every connection
        // starts from a clean state. Backward arcs are re-computed each frame below.
        for (const conn of connections) {
            if (conn.waypoints?.length && !this.userAdjustedConnectionIds.has(conn.id)) {
                this.flowService.updateConnectionWaypoints(conn.id, []);
            }
        }
        // Flush synchronously so nodes and arrows start from the same visual state.
        this.cd.detectChanges();
        this.fFlowComponent?.redraw();

        const DURATION = 400;
        const startTime = performance.now();

        const frame = (now: number): void => {
            const t = Math.min((now - startTime) / DURATION, 1);
            // ease-in-out quadratic
            const eased = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;

            const updatedNodes = nodes
                .filter((n) => newPositions.has(n.id))
                .map((n) => {
                    const from = startPositions.get(n.id) ?? n.position;
                    const to = newPositions.get(n.id)!;
                    return {
                        ...n,
                        position: {
                            x: Math.round(from.x + (to.x - from.x) * eased),
                            y: Math.round(from.y + (to.y - from.y) * eased),
                        },
                    };
                });

            // Update backward arc waypoints each frame using mid-animation node positions
            // (no node-avoidance so the arc stays compact and follows nodes smoothly).
            if (backwardConns.length > 0) {
                const nodeMap = new Map(updatedNodes.map((n) => [n.id, n]));
                for (const conn of backwardConns) {
                    const src = nodeMap.get(conn.sourceNodeId);
                    const tgt = nodeMap.get(conn.targetNodeId);
                    if (!src || !tgt) continue;
                    const srcPort = src.ports?.find((p) => p.id === conn.sourcePortId);
                    const tgtPort = tgt.ports?.find((p) => p.id === conn.targetPortId);
                    const srcPt = getPortPosition(src, srcPort);
                    const tgtPt = getPortPosition(tgt, tgtPort);
                    const arcPts = computeBackwardArcPoints(srcPt, tgtPt, undefined, []);
                    this.flowService.updateConnectionWaypoints(conn.id, [
                        { x: (arcPts[1].x + arcPts[4].x) / 2, y: arcPts[2].y },
                    ]);
                }
            }

            this.flowService.updateNodesInBatch(updatedNodes);
            this.cd.detectChanges();
            this.fFlowComponent?.redraw();

            if (t < 1) {
                this.arrangeAnimationId = requestAnimationFrame(frame);
            } else {
                this.arrangeAnimationId = null;
                // Restore proper segment routing after animation completes
                this.rerouteSegmentConnections();
                setTimeout(() => {
                    this.rerouteSegmentConnections();
                    // Recompute backward arcs without node-avoidance: after a full
                    // rearrange all nodes have moved so the avoidance logic pushes arcs
                    // far outside the visible area. A simple fixed-margin arc looks correct.
                    const finalNodes = this.flowService.nodes();
                    const finalConnections = this.flowService.connections();
                    const bwIds = this.backwardConnectionIds();
                    for (const conn of finalConnections) {
                        if (!bwIds.has(conn.id) || this.userAdjustedConnectionIds.has(conn.id)) continue;
                        const src = finalNodes.find((n) => n.id === conn.sourceNodeId);
                        const tgt = finalNodes.find((n) => n.id === conn.targetNodeId);
                        if (!src || !tgt) continue;
                        const srcPort = src.ports?.find((p) => p.id === conn.sourcePortId);
                        const tgtPort = tgt.ports?.find((p) => p.id === conn.targetPortId);
                        const srcPt = getPortPosition(src, srcPort);
                        const tgtPt = getPortPosition(tgt, tgtPort);
                        const arcPts = computeBackwardArcPoints(srcPt, tgtPt, undefined, []);
                        const waypoint = { x: (arcPts[1].x + arcPts[4].x) / 2, y: arcPts[2].y };
                        this.flowService.updateConnectionWaypoints(conn.id, [waypoint]);
                        this.bumpConnectionRenderVersion(conn.id);
                    }
                    this.cd.detectChanges();
                    this.fFlowComponent?.redraw();
                    this.hasUnarrangedChanges.set(false);

                    //Broadcast nodes order after Auto arrange
                    const nodesAfterArrange = this.flowService.nodes();
                    for (const node of nodesAfterArrange) {
                        this.wsService.sendNodeUpdated(
                            node,
                            this.currentFlowId!,
                            this.flowState.nodes,
                            this.flowService.connections()
                        );
                    }
                    const connectionsAfterArrange = this.flowService.connections();
                    for (const connection of connectionsAfterArrange) {
                        const waypoints = connection.waypoints ?? [];
                        this.wsService.sendConnectionWaypointsUpdated(
                            connection,
                            waypoints,
                            this.getConnectionListKey(connection)
                        );
                    }
                    this._arrangingLock = false;
                    this.isArranging.set(false);
                    if (this.arrangeBtnRef) {
                        this.arrangeBtnRef.nativeElement.disabled = false;
                    }
                }, 0);
            }
        };

        this.arrangeAnimationId = requestAnimationFrame(frame);
    }

    public onDomainClick(): void {
        const startNodeInitialState = this.flowService.startNodeInitialState();

        const dialogRef = this.dialog.open(DomainDialogComponent, {
            width: '1000px',
            height: '800px',
            maxWidth: '90vw',
            maxHeight: '90vh',
            panelClass: 'domain-dialog-panel',
            backdropClass: 'domain-dialog-backdrop',
            data: {
                initialData: startNodeInitialState,
            },
        });

        dialogRef.closed.subscribe((result: unknown) => {
            if (result !== null && typeof result === 'object' && result !== undefined) {
                this.updateStartNodeInitialState(result as Record<string, unknown>);
            }
        });
    }

    public onProjectExpandToggled(project: ProjectNodeModel): void {
        const dialogRef = this.dialog.open(ProjectDialogComponent, {
            width: '90vw',
            height: '90vh',
            data: {
                projectId: project.data.id,
                projectName: project.data.name,
            },
        });

        dialogRef.closed.subscribe(() => {});
    }

    public onFlowPointerDown(event: PointerEvent): void {
        this._dragStartClientX = event.clientX;
        this._dragStartClientY = event.clientY;
        this._dragEndClientX = null;
        this._dragEndClientY = null;
    }

    public onFlowPointerUp(event: PointerEvent): void {
        this._dragEndClientX = event.clientX;
        this._dragEndClientY = event.clientY;
    }

    public onFlowClick(event: MouseEvent): void {
        this.showContextMenu.set(false);
        if (this.multiSelectActive() && !this.isDragging && !(event.target as Element).closest('app-flow-base-node')) {
            this.multiSelectActive.set(false);
            this.selectedNodeIds.set([]);
            this.fFlowComponent.select([], []);
        }
    }

    public onEscapeKey(): void {
        if (this.multiSelectActive()) {
            this.multiSelectActive.set(false);
            this.selectedNodeIds.set([]);
            this.fFlowComponent.select([], []);
        }
    }

    public onToggleMultiSelect(): void {
        const wasActive = this.multiSelectActive();
        this.multiSelectActive.update((v) => !v);
        if (wasActive) {
            this.selectedNodeIds.set([]);
            this.fFlowComponent.select([], []);
        }
    }

    public onSelectionChange(event: { nodeIds: string[] }): void {
        if (this._isReselecting) {
            this._isReselecting = false;
            return;
        }

        const nodeIds = event.nodeIds;

        // In multiselect mode, ignore automatic empty-selection events (e.g. from CDK overlay interactions)
        if (this.multiSelectActive() && nodeIds.length === 0) {
            return;
        }

        const endX = this._dragEndClientX ?? this.mouseCursorPosition.x;
        const endY = this._dragEndClientY ?? this.mouseCursorPosition.y;

        const isLeftToRight =
            nodeIds.length > 0 && this._dragStartClientX !== null && endX - this._dragStartClientX > 10;

        if (isLeftToRight) {
            const selStart = this.fFlowComponent.getPositionInFlow(
                PointExtensions.initialize(this._dragStartClientX!, this._dragStartClientY!)
            );
            const selEnd = this.fFlowComponent.getPositionInFlow(PointExtensions.initialize(endX, endY));
            const selLeft = Math.min(selStart.x, selEnd.x);
            const selRight = Math.max(selStart.x, selEnd.x);
            const selTop = Math.min(selStart.y, selEnd.y);
            const selBottom = Math.max(selStart.y, selEnd.y);

            const allNodes = this.flowService.nodes();
            const containedIds = nodeIds.filter((id) => {
                const node = allNodes.find((n) => n.id === id);
                if (!node) return false;
                return (
                    node.position.x >= selLeft &&
                    node.position.x + (node.size?.width ?? 0) <= selRight &&
                    node.position.y >= selTop &&
                    node.position.y + (node.size?.height ?? 0) <= selBottom
                );
            });

            if (containedIds.length !== nodeIds.length) {
                this._isReselecting = true;
                this.selectedNodeIds.set(containedIds);
                this.fFlowComponent.select(containedIds, []);
                return;
            }
        }

        this.selectedNodeIds.set(nodeIds);
    }

    public onExportSelectedAsJson(): void {
        const selectedIds = this.selectedNodeIds();
        const nodes = this.flowService.nodes();
        const hasUnsaved = selectedIds.some((id) => nodes.find((n) => n.id === id)?.backendId === null);
        if (hasUnsaved) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
            return;
        }
        this.triggerPartialExport(selectedIds);
    }

    public onExportSelectedAsCsv(): void {
        const selectedIds = this.selectedNodeIds();
        const nodes = this.flowService.nodes();

        for (const id of selectedIds) {
            const node = nodes.find((n) => n.id === id);

            if (!node) {
                continue;
            }

            if (node.backendId === null) {
                this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
                continue;
            }

            this.importExportService.cdtExport(node.backendId, 'json').subscribe({
                next: (blob) => {
                    blob.text().then((text) => {
                        const parsed = JSON.parse(text) as Record<string, unknown>;
                        const exportData = this.cdtExportImportService.partialExportNodeToCdtExportData(parsed);
                        const csv = this.cdtExportImportService.exportToCsv(exportData);
                        this.cdtExportImportService.downloadFile(
                            csv,
                            node.node_name + '.csv',
                            'text/csv;charset=utf-8;'
                        );
                    });
                },
                error: () => this.toastService.error('Export failed', 3000, 'bottom-right'),
            });
        }
    }

    public onExportAllAsJson(): void {
        const exportable = this.flowService.nodes().filter((n) => n.type !== NodeType.START && n.type !== NodeType.END);
        if (exportable.length === 0) {
            this.toastService.warning('No nodes to export', 3000, 'bottom-right');
            return;
        }
        if (this.flowService.nodes().some((n) => n.backendId === null)) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
            return;
        }
        this.triggerPartialExport([]);
    }

    public onImportNodes(): void {
        if (!this.currentFlowId) return;
        if (this.hasUnsavedChanges) {
            this.toastService.warning('Save the flow before importing', 3000, 'bottom-right');
            return;
        }
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.value = '';
        input.onchange = (e: Event) => {
            const file = (e.target as HTMLInputElement).files?.[0];
            if (!file || !this.currentFlowId) return;
            this.doPartialImport(file);
        };
        input.click();
    }

    private doPartialImport(file: File): void {
        if (!this.currentFlowId) return;
        this.importExportService.partialImport(this.currentFlowId, file).subscribe({
            next: () => {
                this.toastService.success('Import successful', 3000, 'bottom-right');
                const currentNodes = this.flowService.nodes();
                this._preImportBackendIds = new Set(
                    currentNodes.map((n) => n.backendId).filter((id): id is number => id !== null)
                );
                this._importPositionSnapshot = new Map(
                    currentNodes
                        .filter((n): n is typeof n & { backendId: number } => n.backendId !== null)
                        .map((n) => [n.backendId, { x: n.position.x, y: n.position.y }])
                );
                this.fitAfterNextFlowChange = true;
                this.importComplete.emit();
            },
            error: (err: HttpErrorResponse) => {
                const body = typeof err.error === 'string' ? err.error : JSON.stringify(err.error ?? '');
                const rawMessage =
                    (err.error as Record<string, string>)?.['message'] ??
                    (err.error as Record<string, string>)?.['detail'] ??
                    null;
                if (body.includes('node_name must make a unique set')) {
                    this.toastService.error(
                        'Import failed: a Classification Decision Table node with this name already exists in this flow. This is a backend issue — delete the duplicate CDT nodes and try again.',
                        6000,
                        'bottom-right'
                    );
                } else {
                    this.toastService.error(rawMessage ?? 'Import failed', 3000, 'bottom-right');
                }
            },
        });
    }

    private triggerPartialExport(nodeIds: string[]): void {
        if (!this.currentFlowId) return;
        const body = this.buildPartialExportBody(nodeIds);
        const filename = nodeIds.length > 0 ? 'selected-nodes.json' : 'all-nodes.json';
        this.importExportService.partialExport(this.currentFlowId, body).subscribe({
            next: (blob) => {
                this.downloadBlob(blob, filename);
                const count = Object.entries(body)
                    .filter(([key]) => key !== 'edge_list')
                    .reduce((sum, [, list]) => sum + (list as number[]).length, 0);
                const isExportAll = nodeIds.length === 0;
                const hasStartOrEnd =
                    !isExportAll &&
                    this.flowService
                        .nodes()
                        .some((n) => nodeIds.includes(n.id) && (n.type === NodeType.START || n.type === NodeType.END));
                const suffix = isExportAll || hasStartOrEnd ? ' (Start and End nodes excluded)' : '';
                this.toastService.success(`${count} nodes exported as JSON${suffix}`, 3000, 'bottom-right');
            },
            error: () => this.toastService.error('Export failed', 3000, 'bottom-right'),
        });
    }

    private buildPartialExportBody(selectedIds: string[]): PartialExportRequest {
        const allNodes = this.flowService.nodes();
        const nodes = selectedIds.length > 0 ? allNodes.filter((n) => selectedIds.includes(n.id)) : allNodes;
        const selectedIdSet = new Set(
            nodes.filter((n) => n.type !== NodeType.START && n.type !== NodeType.END).map((n) => n.id)
        );

        const body: PartialExportRequest = {
            start_node_list: [],
            crew_node_list: [],
            python_node_list: [],
            audio_transcription_node_list: [],
            file_extractor_node_list: [],
            end_node_list: [],
            subgraph_node_list: [],
            webhook_trigger_node_list: [],
            telegram_trigger_node_list: [],
            decision_table_node_list: [],
            classification_decision_table_node_list: [],
            graph_note_list: [],
            code_agent_node_list: [],
            schedule_trigger_node_list: [],
            edge_list: [],
        };

        for (const node of nodes) {
            if (node.backendId === null) continue;
            if (node.type === NodeType.START || node.type === NodeType.END) continue;
            const id = node.backendId;
            switch (node.type) {
                case NodeType.AGENT:
                case NodeType.TASK:
                case NodeType.TOOL:
                case NodeType.PROJECT:
                case NodeType.LLM:
                    body.crew_node_list.push(id);
                    break;
                case NodeType.PYTHON:
                    body.python_node_list.push(id);
                    break;
                case NodeType.AUDIO_TO_TEXT:
                    body.audio_transcription_node_list.push(id);
                    break;
                case NodeType.FILE_EXTRACTOR:
                    body.file_extractor_node_list.push(id);
                    break;
                case NodeType.SUBGRAPH:
                    body.subgraph_node_list.push(id);
                    break;
                case NodeType.WEBHOOK_TRIGGER:
                    body.webhook_trigger_node_list.push(id);
                    break;
                case NodeType.TELEGRAM_TRIGGER:
                    body.telegram_trigger_node_list.push(id);
                    break;
                case NodeType.TABLE:
                    body.decision_table_node_list.push(id);
                    break;
                case NodeType.CLASSIFICATION_TABLE:
                    body.classification_decision_table_node_list.push(id);
                    break;
                case NodeType.NOTE:
                    body.graph_note_list.push(id);
                    break;
                case NodeType.CODE_AGENT:
                    body.code_agent_node_list.push(id);
                    break;
                case NodeType.SCHEDULE_TRIGGER:
                    body.schedule_trigger_node_list.push(id);
                    break;
            }
        }

        for (const conn of this.flowService.connections()) {
            if (selectedIdSet.has(conn.sourceNodeId) && selectedIdSet.has(conn.targetNodeId) && conn.data?.id != null) {
                body.edge_list.push(conn.data.id);
            }
        }

        return body;
    }

    private downloadBlob(blob: Blob, filename: string): void {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    public onOpenShortcuts(anchorEl: HTMLElement): void {
        this.openShortcuts.emit(anchorEl.getBoundingClientRect());
    }

    private applyIncomingFlowState(flowState: FlowModel): void {
        const normalizedFlowState = normalizeFlowPorts(flowState);
        this.flowService.setFlow(normalizedFlowState);
        for (const conn of normalizedFlowState.connections) {
            if (conn.userAdjustedWaypoints) {
                this.userAdjustedConnectionIds.add(conn.id);
            } else {
                this.userAdjustedConnectionIds.delete(conn.id);
            }
        }
    }

    private _shiftImportedNodes(flowState: FlowModel, preImportIds: Set<number>): FlowModel {
        const newNodes = flowState.nodes.filter((n) => n.backendId !== null && !preImportIds.has(n.backendId));

        if (!newNodes.length) return flowState;

        const snapshot = this._importPositionSnapshot;
        this._importPositionSnapshot = null;

        // maxRightX uses snapshot positions so previous imports' shifts are respected
        const maxRightX = flowState.nodes
            .filter((n) => n.backendId !== null && preImportIds.has(n.backendId))
            .reduce((max, n) => {
                const pos = snapshot?.get(n.backendId!) ?? n.position;
                return Math.max(max, pos.x + n.size.width);
            }, 0);

        const minNewX = newNodes.reduce((min, n) => Math.min(min, n.position.x), Infinity);
        const offsetX = maxRightX + 400 - minNewX;
        if (offsetX <= 0) return flowState;

        return {
            ...flowState,
            nodes: flowState.nodes.map((n) => {
                if (n.backendId !== null && preImportIds.has(n.backendId)) {
                    const snapshotPos = snapshot?.get(n.backendId);
                    return snapshotPos ? { ...n, position: snapshotPos } : n;
                }
                return { ...n, position: { ...n.position, x: n.position.x + offsetX } };
            }),
        };
    }

    private isDialogOpen(): boolean {
        return this.dialog.openDialogs.length > 0;
    }

    private isEditingLocked(): boolean {
        return this.isDialogOpen();
    }

    private updateStartNodeInitialState(newState: Record<string, unknown>): void {
        const startNode = this.flowService.nodes().find((node) => node.type === NodeType.START) as
            | StartNodeModel
            | undefined;

        if (startNode) {
            const updatedStartNode: StartNodeModel = {
                ...startNode,
                data: {
                    ...startNode.data,
                    initialState: newState,
                },
            };

            this.flowService.updateNode(updatedStartNode);
            this.wsService.sendNodeUpdated(
                updatedStartNode,
                this.currentFlowId!,
                this.flowState.nodes,
                this.flowService.connections()
            );
        } else {
            this.toastService.error('Start node not found');
        }
    }

    public openNodePanel(nodeId: string): void {
        this.sidePanelService.setSelectedNodeId(nodeId);
        afterNextRender(() => this.nodePanelShell?.expandPanel(), { injector: this.injector });
    }

    private toFlowPosition(point: IPoint): IPoint {
        return this.fFlowComponent.getPositionInFlow(PointExtensions.initialize(point.x, point.y));
    }

    private deleteSelections(selections: ICurrentSelection): void {
        if (!selections || (selections.fNodeIds.length === 0 && selections.fConnectionIds.length === 0)) {
            console.warn('No items selected to delete.');
            return;
        }

        this.recordAfterChange();

        const nodeIdsToDelete = selections.fNodeIds.filter((nodeId) => {
            const node = this.flowService.nodes().find((n) => n.id === nodeId);
            return node && node.type !== NodeType.START;
        });

        // Snapshot before deletion — connection list_key resolution needs the
        // source node, which is gone from the flow state after the delete.
        const nodesBeforeDelete = this.flowService.nodes();
        const { removedNodes, removedConnections } = this.flowService.deleteSelections({
            fNodeIds: nodeIdsToDelete,
            fConnectionIds: selections.fConnectionIds,
        });

        const nodeRefs = removedNodes
            .map((node) => this.buildNodeDeleteRef(node))
            .filter((r): r is EntryDeleteRef => r !== null);
        const decisionRoutingSourceIds = new Set<string>();
        const connectionRefs: EntryDeleteRef[] = [];
        for (const conn of removedConnections) {
            const sourceNode = nodesBeforeDelete.find((n) => n.id === conn.sourceNodeId);
            if (this.isDecisionRoutingSource(sourceNode?.type)) {
                decisionRoutingSourceIds.add(conn.sourceNodeId);
            } else {
                connectionRefs.push(this.buildConnectionDeleteRef(conn, nodesBeforeDelete));
            }
        }
        if (nodeRefs.length > 0) {
            this.wsService.sendNodesDeleted(nodeRefs);
        }
        if (connectionRefs.length > 0) {
            this.wsService.sendConnectionsDeleted(connectionRefs);
        }
        const removedNodeIds = new Set(removedNodes.map((n) => n.id));
        for (const id of decisionRoutingSourceIds) {
            if (!removedNodeIds.has(id)) {
                this.broadcastDecisionRoutingUpdate(id);
            }
        }

        if (selections.fNodeIds.length > 0) {
            this.selectedNodeIds.set([]);
            this.fFlowComponent.select([], []);
        }
    }

    private broadcastFlowDiff(diff: FlowDiffResult): void {
        if (this.currentFlowId == null) return;
        const graphId = this.currentFlowId;
        const allNodes = this.flowService.nodes();
        const allConnections = this.flowService.connections();
        const lookupNodes = [...allNodes, ...diff.deletedNodes];

        const nodeRefs = diff.deletedNodes
            .map((node) => this.buildNodeDeleteRef(node))
            .filter((r): r is EntryDeleteRef => r !== null);
        if (nodeRefs.length > 0) {
            this.wsService.sendNodesDeleted(nodeRefs);
        }

        const connectionRefs = diff.deletedConnections
            .filter((conn) => {
                const sourceNode = lookupNodes.find((n) => n.id === conn.sourceNodeId);
                return !this.isDecisionRoutingSource(sourceNode?.type);
            })
            .map((conn) => this.buildConnectionDeleteRef(conn, lookupNodes));
        if (connectionRefs.length > 0) {
            this.wsService.sendConnectionsDeleted(connectionRefs);
        }

        for (const node of diff.createdNodes) {
            this.wsService.sendNodeCreated(node, graphId, allNodes, allConnections);
        }

        for (const node of diff.updatedNodes) {
            this.wsService.sendNodeUpdated(node, graphId, allNodes, allConnections);
        }

        for (const conn of diff.createdConnections) {
            const sourceNode = allNodes.find((n) => n.id === conn.sourceNodeId);
            const targetNode = allNodes.find((n) => n.id === conn.targetNodeId);
            if (!sourceNode || !targetNode) continue;
            if (this.isDecisionRoutingSource(sourceNode.type)) continue;
            this.wsService.sendConnectionCreated(
                conn,
                this.getConnectionListKey(conn, allNodes),
                sourceNode,
                targetNode,
                graphId
            );
        }
    }

    public resyncAfterReconnect(serverFlow: FlowModel, baseFlow: FlowModel): void {
        if (this.currentFlowId == null) return;
        const localFlow = this.flowService.getFlowState();
        const myChanges = diffFlowModels(baseFlow, localFlow);

        this.flowService.setFlow(serverFlow);

        for (const node of myChanges.createdNodes) {
            this.flowService.addNode(node);
        }
        for (const node of myChanges.updatedNodes) {
            this.flowService.updateNode(node);
        }
        for (const node of myChanges.deletedNodes) {
            this.flowService.deleteSelections({ fNodeIds: [node.id], fConnectionIds: [] });
        }
        for (const conn of myChanges.createdConnections) {
            this.flowService.addConnection(conn);
        }
        for (const conn of myChanges.deletedConnections) {
            this.flowService.deleteSelections({ fNodeIds: [], fConnectionIds: [conn.id] });
        }

        this.broadcastFlowDiff(myChanges);
    }

    private recordAfterChange(): void {
        const before = JSON.parse(JSON.stringify(this.flowService.getFlowState())) as FlowModel;
        queueMicrotask(() => {
            const after = this.flowService.getFlowState();
            this.undoRedoService.record(this.buildUndoEntry(before, after));
        });
    }

    private buildUndoEntry(before: FlowModel, after: FlowModel): UndoEntry {
        const nodes: NodeChange[] = [];
        const beforeNodes = new Map<string, NodeModel>(before.nodes.map((n) => [n.id, n]));
        const afterNodes = new Map<string, NodeModel>(after.nodes.map((n) => [n.id, n]));
        for (const [id, a] of afterNodes) {
            const b = beforeNodes.get(id);
            if (!b) nodes.push({ before: null, after: a });
            else if (JSON.stringify(b) != JSON.stringify(a)) nodes.push({ before: b, after: a });
        }
        for (const [id, b] of beforeNodes) {
            if (!afterNodes.has(id)) nodes.push({ before: b, after: null });
        }

        const connections: ConnectionChange[] = [];
        const beforeConns = new Map<string, ConnectionModel>(before.connections.map((c) => [c.id, c]));
        const afterConns = new Map<string, ConnectionModel>(after.connections.map((c) => [c.id, c]));
        for (const [id, a] of afterConns) {
            if (!beforeConns.has(id)) connections.push({ before: null, after: a });
        }
        for (const [id, b] of beforeConns) {
            if (!afterConns.has(id)) connections.push({ before: b, after: null });
        }

        return { nodes, connections };
    }

    private applyUndoEntry(entry: UndoEntry, direction: 'undo' | 'redo'): void {
        const pick = (c: { before: unknown; after: unknown }) => (direction === 'undo' ? c.before : c.after);
        const other = (c: { before: unknown; after: unknown }) => (direction === 'undo' ? c.after : c.before);

        const graphId = this.currentFlowId!;

        // create + update node
        for (const nc of entry.nodes) {
            const target = pick(nc) as NodeModel | null;
            const source = other(nc) as NodeModel | null;
            if (target && source) {
                this.flowService.updateNode(target);
                const opId = this.wsService.sendNodeUpdated(
                    target,
                    graphId,
                    this.flowService.nodes(),
                    this.flowService.connections(),
                    source,
                    true
                );
                if (opId) this.pendingUndoOps.set(opId, { revert: source, entry, direction });
            } else if (target && !source) {
                this.flowService.addNode(target);
                this.wsService.sendNodeCreated(
                    target,
                    graphId,
                    this.flowService.nodes(),
                    this.flowService.connections()
                );
            }
        }

        //create connection
        for (const cc of entry.connections) {
            const target = pick(cc) as ConnectionModel | null;
            const source = other(cc) as ConnectionModel | null;
            if (target && !source) {
                this.flowService.addConnection(target);
                const nodes = this.flowService.nodes();
                const src = nodes.find((n) => n.id === target.sourceNodeId);
                const tgt = nodes.find((n) => n.id === target.targetNodeId);
                if (src && tgt) {
                    if (this.isDecisionRoutingSource(src.type)) {
                        this.broadcastDecisionRoutingUpdate(src.id);
                    } else {
                        this.wsService.sendConnectionCreated(
                            target,
                            this.getConnectionListKey(target),
                            src,
                            tgt,
                            graphId
                        );
                    }
                }
            }
        }

        //delete connection
        for (const cc of entry.connections) {
            const target = pick(cc) as ConnectionModel | null;
            const source = other(cc) as ConnectionModel | null;
            if (!target && source) {
                this.flowService.deleteSelections({ fNodeIds: [], fConnectionIds: [source.id] });
                const nodes = this.flowService.nodes();
                const src = nodes.find((n) => n.id === source.sourceNodeId);
                if (src && this.isDecisionRoutingSource(src.type)) {
                    this.broadcastDecisionRoutingUpdate(src.id);
                } else {
                    this.wsService.sendConnectionsDeleted([this.buildConnectionDeleteRef(source, nodes)]);
                }
            }
        }

        //delete node
        for (const nc of entry.nodes) {
            const target = pick(nc) as NodeModel | null;
            const source = other(nc) as NodeModel | null;
            if (!target && source) {
                this.flowService.deleteSelections({ fNodeIds: [source.id], fConnectionIds: [] });
                const ref = this.buildNodeDeleteRef(source);
                if (ref) this.wsService.sendNodesDeleted([ref]);
            }
        }
    }

    private resolveTableOverlaps(node: NodeModel): string[] {
        if (node.type !== NodeType.TABLE) {
            return [];
        }

        const movedNodes = resolveOverlapsForNode(node.id, this.flowService.nodes());

        if (movedNodes.length > 0) {
            this.flowService.updateNodesInBatch(movedNodes);
        }

        return movedNodes.map((movedNode) => movedNode.id);
    }

    private snapToGrid(value: number): number {
        return Math.round(value / this.GRID_CELL_SIZE) * this.GRID_CELL_SIZE;
    }

    private findNearestFreePosition(
        position: IPoint,
        bounds: ReturnType<typeof getCollisionBounds>,
        nodes: NodeModel[]
    ): IPoint {
        return findNearestFreePosition(position, bounds, nodes);
    }

    private getCollisionBounds(node: NodeModel) {
        return getCollisionBounds(node);
    }

    private ensureNodeSize(node: NodeModel): NodeModel {
        return normalizeTableNodeSize(node);
    }

    private getDecisionTableVisualHeight(node: NodeModel): number {
        return normalizeTableNodeSize(node).size.height;
    }

    private getConnectionListKey(connection: ConnectionModel, nodes: NodeModel[] = this.flowService.nodes()): string {
        // TABLE is intentionally NOT here: decision-table routing lives inside
        // the node entity and is broadcast via broadcastDecisionRoutingUpdate,
        // never as an edge/conditional-edge entry.
        const sourceNode = nodes.find((n) => n.id === connection.sourceNodeId);
        return sourceNode?.type === NodeType.EDGE ? 'conditional_edge_list' : 'edge_list';
    }

    // Connections sourced from these node types are not edges: their routing
    // (default/error/per-group next_node) is persisted inside the node entity.
    private isDecisionRoutingSource(nodeType: NodeType | undefined): boolean {
        return nodeType === NodeType.TABLE || nodeType === NodeType.CLASSIFICATION_TABLE;
    }

    // Decision/classification table routing is persisted inside the node
    // entity, not as edge rows — connection changes whose source is such a
    // table are broadcast as node_updated of that node.
    private broadcastDecisionRoutingUpdate(sourceNodeId: string): void {
        const tableNode = this.flowService.nodes().find((n) => n.id === sourceNodeId);
        if (tableNode) {
            this.wsService.sendNodeUpdated(
                tableNode,
                this.currentFlowId!,
                this.flowService.nodes(),
                this.flowService.connections()
            );
        }
    }

    private buildNodeDeleteRef(node: NodeModel): EntryDeleteRef | null {
        const list_key = nodeTypeToListKey(node.type);
        if (!list_key) return null;
        return node.backendId != null ? { list_key, id: node.backendId } : { list_key, temp_id: node.id };
    }

    private buildConnectionDeleteRef(
        connection: ConnectionModel,
        nodes: NodeModel[] = this.flowService.nodes()
    ): EntryDeleteRef {
        const list_key = this.getConnectionListKey(connection, nodes);
        return connection.data?.id != null
            ? { list_key, id: connection.data.id }
            : { list_key, temp_id: connection.id };
    }

    private normalizeWaypointsForConnection(connection: ConnectionModel, waypoints: IPoint[] | undefined): IPoint[] {
        return normalizeConnectionWaypoints(connection, this.flowService.nodes(), waypoints);
    }

    private bumpConnectionRenderVersion(connectionId: string): void {
        this.connectionRenderVersions.update((v) => ({
            ...v,
            [connectionId]: (v[connectionId] ?? 0) + 1,
        }));
    }

    private syncAfterAutoAlign(affectedNodeIds: Set<string>): void {
        const affectedConnectionIds = this.flowService
            .connections()
            .filter(
                (connection) =>
                    affectedNodeIds.has(connection.sourceNodeId) || affectedNodeIds.has(connection.targetNodeId)
            )
            .map((connection) => connection.id);

        if (affectedConnectionIds.length === 0) {
            this.rerouteSegmentConnections();
            this.cd.detectChanges();
            this.fFlowComponent?.redraw();
            return;
        }

        this.hiddenConnectionIds.set(new Set(affectedConnectionIds));
        this.cd.detectChanges();
        this.fFlowComponent?.redraw();

        requestAnimationFrame(() => {
            this.rerouteSegmentConnections();

            for (const connectionId of affectedConnectionIds) {
                this.bumpConnectionRenderVersion(connectionId);
            }

            this.hiddenConnectionIds.set(new Set<string>());
            this.cd.detectChanges();

            requestAnimationFrame(() => {
                this.fFlowComponent?.redraw();
            });
        });
    }

    public commitOpenPanelToFlow(): boolean {
        const updatedNode = this.nodePanelShell?.captureCurrentNodeState();
        if (!updatedNode) return false;
        if (!this.flowService.nodes().some((n) => n.id === updatedNode.id)) return false;
        this.onNodePanelAutosaved(updatedNode);
        return true;
    }
}
