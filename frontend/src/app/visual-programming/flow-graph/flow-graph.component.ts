import { Dialog } from '@angular/cdk/dialog';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
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
import { IPoint, PointExtensions } from '@foblex/2d';
import {
    EFMarkerType,
    EFResizeHandleType,
    EFZoomDirection,
    F_CONNECTION_BUILDERS,
    FCanvasComponent,
    FConnectionContent,
    FConnectionGradient,
    FConnectionWaypoints,
    FCreateConnectionEvent,
    FCreateNodeEvent,
    FDragNodeStartEventData,
    FDragStartedEvent,
    FFlowComponent,
    FFlowModule,
    FReassignConnectionEvent,
    FZoomDirective,
    ICurrentSelection,
} from '@foblex/flow';
import { Subject } from 'rxjs';

import { ToastService } from '../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../shared/components/app-svg-icon/app-svg-icon.component';
import { ToggleSwitchComponent } from '../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { DomainDialogComponent } from '../components/domain-dialog/domain-dialog.component';
import { FlowActionPanelComponent } from '../components/flow-action-panel/flow-action-panel.component';
import { FlowBaseNodeComponent } from '../components/flow-base-node/flow-base-node.component';
import { FlowFilesButtonComponent } from '../components/flow-files-button/flow-files-button.component';
import { FlowGraphContextMenuComponent } from '../components/flow-graph-context-menu/flow-graph-context-menu.component';
import { FlowShortcutsButtonComponent } from '../components/flow-shortcuts-button/flow-shortcuts-button.component';
import { NodePanelShellComponent } from '../components/node-panels/node-panel-shell/node-panel-shell.component';
import { NodesSearchComponent } from '../components/nodes-search/nodes-search.component';
import { NoteEditDialogComponent } from '../components/note-edit-dialog/note-edit-dialog.component';
import { ProjectDialogComponent } from '../components/project-dialog/project-dialog.component';
import { MouseTrackerDirective } from '../core/directives/mouse-tracker.directive';
import { ShortcutListenerDirective } from '../core/directives/shortcut-listener.directive';
import { WaypointTooltipDirective } from '../core/directives/waypoint-tooltip.directive';
import { NodeType } from '../core/enums/node-type';
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
        ToggleSwitchComponent,
        FConnectionGradient,
        FConnectionContent,
        FConnectionWaypoints,
        WaypointTooltipDirective,
        FlowFilesButtonComponent,
    ],
})
export class FlowGraphComponent implements OnInit, OnChanges, OnDestroy {
    @Input() flowState!: FlowModel;
    @Input() currentFlowId: number | null = null;
    @Input() flowName: string = '';
    @Input() initialNodeId: string | null = null;

    @Output() save = new EventEmitter<FlowModel>();
    readonly openShortcuts = output<DOMRect>();

    @ViewChild(FFlowComponent, { static: false })
    private fFlowComponent!: FFlowComponent;

    @ViewChild(FCanvasComponent, { static: true })
    private fCanvasComponent!: FCanvasComponent;

    @ViewChild(FZoomDirective, { static: true })
    private fZoomDirective!: FZoomDirective;

    @ViewChild('nodePanelShell', { static: false })
    private nodePanelShell?: NodePanelShellComponent;

    readonly GRID_CELL_SIZE = GRID_CELL_SIZE;
    protected readonly getMinimapClassForNode = getMinimapClassForNode;
    protected readonly eMarkerType = EFMarkerType;
    protected readonly CONNECTION_DELETE_BUTTON_POSITION = 0.56;
    protected readonly eResizeHandleType = EFResizeHandleType;
    protected readonly NodeType = NodeType;

    protected mouseCursorPosition: IPoint = { x: 0, y: 0 };
    protected contextMenuPosition = signal<IPoint>({ x: 0, y: 0 });
    protected isLoaded = signal(false);
    protected showContextMenu = signal(false);
    protected showVariables = signal(false);
    public smartRoutingEnabled = signal<boolean>(false);

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
    private readonly injector = inject(Injector);

    constructor() {}

    public ngOnInit(): void {
        this.applyIncomingFlowState(this.flowState);
        if (this.initialNodeId) {
            this.openNodePanel(this.initialNodeId);
        }
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['flowState'] && !changes['flowState'].firstChange) {
            this.applyIncomingFlowState(this.flowState);
        }
        if (changes['initialNodeId'] && changes['initialNodeId'].currentValue) {
            this.openNodePanel(changes['initialNodeId'].currentValue);
        }
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    public onInitialized(): void {
        this.isLoaded.set(true);
        setTimeout(() => {
            this.rerouteSegmentConnections();
            this.cd.detectChanges();
        }, 0);
    }

    public onReassignConnection(event: FReassignConnectionEvent): void {
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
        if (this.isDialogOpen()) {
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
        if (this.isDialogOpen()) {
            return;
        }

        this.undoRedoService.onUndo();
    }

    public onRedo(): void {
        if (this.isDialogOpen()) {
            return;
        }

        this.undoRedoService.onRedo();
    }

    public onDelete(): void {
        if (this.isDialogOpen()) {
            return;
        }

        const selections: ICurrentSelection = this.fFlowComponent.getSelection();
        this.deleteSelections(selections);
    }

    public onDeleteConnection(event: MouseEvent, connectionId: string): void {
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
        this.commitSidePanelToFlow();
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

        const dragData = event.data as FDragNodeStartEventData | undefined;
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

    public toggleShowVariables(): void {
        this.showVariables.set(!this.showVariables());
    }

    public updateMouseTrackerPosition(event: IPoint): void {
        this.mouseCursorPosition = event;
    }

    public onSmartRoutingToggle(value: boolean): void {
        this.smartRoutingEnabled.set(value);
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

    private isDialogOpen(): boolean {
        return this.dialog.openDialogs.length > 0;
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

    private openNodePanel(nodeId: string): void {
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

        this.undoRedoService.stateChanged();

        const nodeIdsToDelete = selections.fNodeIds.filter((nodeId) => {
            const node = this.flowService.nodes().find((n) => n.id === nodeId);
            return node && node.type !== NodeType.START;
        });

        this.flowService.deleteSelections({
            fNodeIds: nodeIdsToDelete,
            fConnectionIds: selections.fConnectionIds,
        });
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
