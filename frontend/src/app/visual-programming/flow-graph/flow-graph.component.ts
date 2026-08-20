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
    FCanvasComponent,
    FCreateConnectionEvent,
    FCreateNodeEvent,
    FDragStartedEvent,
    FFlowComponent,
    FFlowModule,
    FReassignConnectionEvent,
    FZoomDirective,
    ICurrentSelection,
} from '@foblex/flow';
import { Subject } from 'rxjs';

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
import { UndoRedoService } from '../services/undo-redo.service';
import { createFlowConnection } from '../utils/connection.factory';
import { normalizeFlowPorts } from '../utils/load';

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
        MatTooltipModule,
    ],
})
export class FlowGraphComponent implements OnInit, OnChanges, OnDestroy {
    @Input() flowState!: FlowModel;
    @Input() currentFlowId: number | null = null;
    @Input() flowName: string = '';
    @Input() initialNodeId: string | null = null;
    @Input() initialNodeExpand: boolean = true;
    @Input() isSaving: boolean = false;
    @Input() hasUnsavedChanges: boolean = false;

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

    private lastSeenFullSaveRequest = 0;

    constructor() {
        effect(() => {
            const requestCount = this.sidePanelService.fullSaveRequest();
            if (requestCount > this.lastSeenFullSaveRequest) {
                this.lastSeenFullSaveRequest = requestCount;
                this.emitSave();
            }
        });
    }

    public ngOnInit(): void {
        this.applyIncomingFlowState(this.flowState);
        if (this.initialNodeId) {
            this.openNodePanel(this.initialNodeId, this.initialNodeExpand);
        }
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
            this.openNodePanel(changes['initialNodeId'].currentValue, this.initialNodeExpand);
        }
        if (changes['isSaving'] && changes['isSaving'].currentValue === true) {
            this.onCloseContextMenu();
        }
    }

    public ngOnDestroy(): void {
        if (this.arrangeAnimationId !== null) {
            cancelAnimationFrame(this.arrangeAnimationId);
        }
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

        this.undoRedoService.stateChanged();

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

        this.flowService.removeConnection(event.connectionId);
        this.flowService.addConnection(updatedConnection);

        this.toastService.success('Connection reassigned successfully', 3000, 'bottom-right');
    }

    public onConnectionAdded(event: FCreateConnectionEvent): void {
        this.hasUnarrangedChanges.set(true);
        this.undoRedoService.stateChanged();

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

        const allPorts = this.flowService.nodes().flatMap((n) => n.ports ?? []);
        const sourcePort = allPorts.find((p) => p.id === pair.sourcePortId);
        const targetPort = allPorts.find((p) => p.id === pair.targetPortId);
        const sourceOccupied =
            !!sourcePort &&
            !sourcePort.multiple &&
            currentConnections.some((conn) => conn.sourcePortId === pair.sourcePortId);
        const targetOccupied =
            !!targetPort &&
            !targetPort.multiple &&
            currentConnections.some((conn) => conn.targetPortId === pair.targetPortId);
        if (sourceOccupied || targetOccupied) {
            this.toastService.warning('This port already has a connection', 4000, 'bottom-right');
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

        this.undoRedoService.stateChanged();
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
            placedNodes.push(updatedNode);
        }

        const newNodeIds = newNodes.map((node) => node.id);
        const newConnectionIds = newConnections.map((conn) => conn.id);

        setTimeout(() => {
            this.fFlowComponent.select(newNodeIds, newConnectionIds);
        }, 0);
    }

    public onUndo(): void {
        if (this.isEditingLocked()) {
            return;
        }

        this.hasUnarrangedChanges.set(true);
        this.undoRedoService.onUndo();
    }

    public onRedo(): void {
        if (this.isEditingLocked()) {
            return;
        }

        this.hasUnarrangedChanges.set(true);
        this.undoRedoService.onRedo();
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
        this.undoRedoService.stateChanged();
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
        const normalizedNode = normalizeTableNodeSize(updatedNode);
        this.flowService.updateNode(normalizedNode);
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
        const normalizedNode = normalizeTableNodeSize(updatedNode);
        this.flowService.updateNode(normalizedNode);
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

    public commitSidePanelToFlow(): void {
        const updatedNode = this.nodePanelShell?.captureCurrentNodeState();
        if (updatedNode) {
            this.flowService.updateNode(updatedNode);
        }
    }

    public emitSave(): void {
        if (this.nodePanelShell?.hasPanelInstance()) {
            // Use the validation-aware capture. Most panels (e.g. the task node panel) always
            // get a node back here — even when their form is invalid — so their own invalid
            // state can be reported by a flow-wide validation + blocking toast further down
            // the save pipeline instead of a hard client-side abort. A panel with its own hard
            // client-side validation that must never reach the backend (e.g. the
            // schedule-trigger panel's date/timezone checks) can override
            // `captureForValidation()` to return `null` on failure — which aborts the entire
            // save right here (no request sent), matching this panel's pre-existing behavior.
            const updatedNode = this.nodePanelShell.captureCurrentNodeStateForSave();
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
        this.undoRedoService.stateChanged();

        const updatedNode = {
            ...node,
            size: {
                width: event.width,
                height: event.height,
            },
        };

        this.flowService.updateNode(updatedNode);
    }

    public onDragStarted(event: FDragStartedEvent): void {
        this.isDragging = true;
        this.draggingElements.clear();

        const dragData = event.fData as { fNodeIds?: string[] } | undefined;
        if (dragData?.fNodeIds) {
            dragData.fNodeIds.forEach((id: string) => this.draggingElements.add(id));
        }

        this.undoRedoService.stateChanged();
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
                autoAlignedNodeIds.add(id);
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
            this.undoRedoService.stateChanged();
        }

        const updatedNode = {
            ...node,
            position: {
                x: this.snapToGrid(newPos.x),
                y: this.snapToGrid(newPos.y),
            },
        };

        this.flowService.updateNode(updatedNode);
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

        this.undoRedoService.stateChanged();

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
            crew_node_list: [],
            agent_node_list: [],
            task_node_list: [],
            python_node_list: [],
            audio_transcription_node_list: [],
            file_extractor_node_list: [],
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
                    body.agent_node_list.push(id);
                    break;
                case NodeType.TASK:
                    body.task_node_list.push(id);
                    break;
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

    // Editing is locked while a dialog is open OR a full graph save is in flight.
    // (Saving lock fixes edits made mid-save being discarded when the response is applied.)
    private isEditingLocked(): boolean {
        return this.isDialogOpen() || this.isSaving;
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
        } else {
            this.toastService.error('Start node not found');
        }
    }

    public openNodePanel(nodeId: string, expand: boolean = true): void {
        this.sidePanelService.setSelectedNodeId(nodeId);
        if (!expand) return;
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

        this.undoRedoService.stateChanged();

        const nodeIdsToDelete = selections.fNodeIds.filter((nodeId) => {
            const node = this.flowService.nodes().find((n) => n.id === nodeId);
            return node && node.type !== NodeType.START;
        });

        this.flowService.deleteSelections({
            fNodeIds: nodeIdsToDelete,
            fConnectionIds: selections.fConnectionIds,
        });

        if (selections.fNodeIds.length > 0) {
            this.selectedNodeIds.set([]);
            this.fFlowComponent.select([], []);
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
}
