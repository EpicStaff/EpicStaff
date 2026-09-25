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
    untracked,
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
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, NodeType, ResourceCode } from '@shared/models';
import { Subject } from 'rxjs';

import { ImportExportService, PartialExportRequest } from '../../core/services/import-export.service';
import { ToastService } from '../../services/notifications';
import { DomainDialogComponent, DomainDialogData } from '../components/domain-dialog/domain-dialog.component';
import { FlowActionPanelComponent } from '../components/flow-action-panel/flow-action-panel.component';
import { FlowBaseNodeComponent } from '../components/flow-base-node/flow-base-node.component';
import { FlowExportImportButtonComponent } from '../components/flow-export-import-button/flow-export-import-button.component';
import { FlowFilesButtonComponent } from '../components/flow-files-button/flow-files-button.component';
import { FlowGraphContextMenuComponent } from '../components/flow-graph-context-menu/flow-graph-context-menu.component';
import {
    FlowSettingsPanelComponent,
    FlowSettingsPanelData,
} from '../components/flow-settings-panel/flow-settings-panel.component';
import { FlowShortcutsButtonComponent } from '../components/flow-shortcuts-button/flow-shortcuts-button.component';
import { CdtExportImportService } from '../components/node-panels/classification-decision-table-node-panel/cdt-export-import.service';
import { NodePanelShellComponent } from '../components/node-panels/node-panel-shell/node-panel-shell.component';
import { NodesSearchComponent } from '../components/nodes-search/nodes-search.component';
import { NoteEditDialogComponent } from '../components/note-edit-dialog/note-edit-dialog.component';
import { MouseTrackerDirective } from '../core/directives/mouse-tracker.directive';
import { ShortcutListenerDirective } from '../core/directives/shortcut-listener.directive';
import { WaypointTooltipDirective } from '../core/directives/waypoint-tooltip.directive';
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
import { FlowViewport } from '../core/models/flow-viewport.model';
import { GraphNoteModel, NodeModel, StartNodeModel } from '../core/models/node.model';
import { CreateNodeRequest } from '../core/models/node-creation.types';
import { CustomPortId } from '../core/models/port.model';
import { FLOW_EDITOR_READ_ONLY } from '../core/providers/flow-editor-state.providers';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { FlowSettingsService } from '../services/flow-settings.service';
import { NodeFactoryService } from '../services/node-factory.service';
import { SidePanelService } from '../services/side-panel.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { createFlowConnection } from '../utils/connection.factory';
import { normalizeFlowPorts } from '../utils/load';

interface ConnectionEndGrab {
    connection: ConnectionModel;
    group: ConnectionModel[];
    endpoint: 'source' | 'target';
    fromPort: boolean;
}

function waypointsEqual(a: IPoint[], b: IPoint[]): boolean {
    if (a.length !== b.length) return false;
    return a.every((p, i) => p.x === b[i].x && p.y === b[i].y);
}

@Component({
    selector: 'app-flow-graph',
    templateUrl: './flow-graph.component.html',
    styleUrls: ['../styles/_variables.scss', './flow-graph.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '(document:pointerup)': 'resetReassignHighlight()',
        '(document:pointercancel)': 'resetReassignHighlight()',
    },
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
        HasPermissionDirective,
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
    /** Applied once the canvas loads, instead of fitting the flow to the screen. */
    @Input() initialViewport: FlowViewport | null = null;

    @Output() save = new EventEmitter<FlowModel>();
    @Output() requestReload = new EventEmitter<void>();
    readonly openShortcuts = output<DOMRect>();
    /** Nodes were copied into this editor's clipboard. */
    readonly copied = output<void>();
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

    @ViewChild(NodesSearchComponent) private nodesSearchComponent?: NodesSearchComponent;

    public closeNodesSearch(): void {
        this.nodesSearchComponent?.closeSearch();
    }

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
        this.multiSelectActive() || (event instanceof MouseEvent && (event.shiftKey || event.ctrlKey || event.metaKey));

    readonly selectionAreaTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        this.multiSelectActive() || (event instanceof MouseEvent && event.shiftKey);

    readonly canvasMoveTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        !this.multiSelectActive() && !(event instanceof MouseEvent && event.shiftKey);

    /** Gates every Foblex gesture that edits the graph (move, resize, rotate, connect, reassign, waypoints). */
    readonly editGestureTrigger = (): boolean => !this.isReadOnly;

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

    protected readonly frozenConnectionIds = computed<Set<string>>(() => {
        const ids = new Set<string>();

        for (const conn of this.flowService.connections()) {
            if (conn.userAdjustedWaypoints) {
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
    private readonly previousBackwardConnectionIds = new Set<string>();
    private draggedNodeIds = new Set<string>();
    private draggingElements = new Set<string>();
    private isDragging = false;
    protected readonly connectionRenderVersions = signal<Record<string, number>>({});
    private readonly hiddenConnectionIds = signal<Set<string>>(new Set<string>());
    protected readonly reassignSuppressedConnectionIds = signal<ReadonlySet<string>>(new Set<string>());
    protected readonly reassignFollowerIds = signal<ReadonlySet<string>>(new Set<string>());
    private reassignGroupIds: string[] = [];

    protected readonly isReadOnly = inject(FLOW_EDITOR_READ_ONLY);
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
    private readonly hostElement = inject<ElementRef<HTMLElement>>(ElementRef);

    // Start from the current count so a canvas re-created after an earlier save request
    // (e.g. when leaving version preview) does not replay it. untracked: this initialiser runs
    // while the parent template is rendering and must not subscribe that view to the signal.
    private lastSeenFullSaveRequest = untracked(() => this.sidePanelService.fullSaveRequest());

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
            if (this.initialViewport) {
                this.applyViewport(this.initialViewport);
            } else {
                this.fCanvasComponent.fitToScreen({ x: 200, y: 100 }, false);
                if (this.flowService.nodes().length === 1) {
                    this.fCanvasComponent.setScale(0.1);
                }
            }
            this.cd.detectChanges();
        }, 0);
    }

    /** The current pan and zoom, or null before the canvas exists. */
    public captureViewport(): FlowViewport | null {
        const transform = this.fCanvasComponent?.transform;
        if (!transform) return null;
        return { position: PointExtensions.sum(transform.position, transform.scaledPosition), scale: transform.scale };
    }

    public onFlowMouseDown(event: MouseEvent): void {
        const isPlainPress =
            event.button === 0 && !event.shiftKey && !this.multiSelectActive() && !this.isEditingLocked();
        const grab = isPlainPress && !event.ctrlKey && !event.metaKey ? this.resolveConnectionEndGrab(event) : null;

        this.reassignGroupIds = grab?.group.map((conn) => conn.id) ?? [];
        this.suppressReassignOfNeighbours(grab);

        if (!grab?.fromPort) {
            return;
        }

        const connectionElement = this.findConnectionElement(grab.connection.id);
        const handle = connectionElement && this.getDragHandle(connectionElement, grab.endpoint);
        if (!handle) {
            return;
        }

        const { left, top, width, height } = handle.getBoundingClientRect();
        // Foblex starts a reassign only when mousedown lands on a connection drag handle, so the grab point is moved onto it.
        Object.defineProperties(event, {
            clientX: { value: left + width / 2 },
            clientY: { value: top + height / 2 },
        });
    }

    private resolveConnectionEndGrab(event: MouseEvent): ConnectionEndGrab | null {
        const target = event.target as Element | null;

        const connectionElement = target?.closest('f-connection');
        if (connectionElement) {
            return this.resolveHandleGrab(connectionElement, event);
        }

        const portElement = target?.closest<HTMLElement>('[data-f-output-id], [data-f-input-id]');
        const portId = portElement?.dataset['fOutputId'] ?? portElement?.dataset['fInputId'];
        return portId ? this.resolvePortGrab(portId) : null;
    }

    private resolveHandleGrab(connectionElement: Element, event: MouseEvent): ConnectionEndGrab | null {
        const connection = this.flowService.connections().find((conn) => conn.id === connectionElement.id);
        if (!connection) {
            return null;
        }

        const endpoint = (['target', 'source'] as const).find((end) => {
            const handle = this.getDragHandle(connectionElement, end);
            if (!handle) {
                return false;
            }
            const { left, top, width, height } = handle.getBoundingClientRect();
            const radius = width / 2;
            return (event.clientX - (left + radius)) ** 2 + (event.clientY - (top + height / 2)) ** 2 <= radius ** 2;
        });
        if (!endpoint) {
            return null;
        }

        const selectedIds = this.getSelectedConnectionIds();
        const portId = endpoint === 'source' ? connection.sourcePortId : connection.targetPortId;
        const selectedAtPort = selectedIds.has(connection.id)
            ? this.connectionsAtPort(portId).filter((conn) => conn.id !== connection.id && selectedIds.has(conn.id))
            : [];

        return { connection, group: [connection, ...selectedAtPort], endpoint, fromPort: false };
    }

    private resolvePortGrab(portId: string): ConnectionEndGrab | null {
        const port = this.flowService
            .nodes()
            .flatMap((node) => node.ports ?? [])
            .find((p) => p.id === portId);
        if (!port) {
            return null;
        }

        const attached = this.connectionsAtPort(portId);
        const selectedIds = this.getSelectedConnectionIds();
        const selected = attached.filter((conn) => selectedIds.has(conn.id));
        const canMoveAll = port.port_type === 'input' || !port.multiple;
        const group = selected.length > 0 ? selected : canMoveAll ? attached : [];
        if (group.length === 0) {
            return null;
        }

        const [connection] = group;
        return {
            connection,
            group,
            endpoint: connection.sourcePortId === portId ? 'source' : 'target',
            fromPort: true,
        };
    }

    private getSelectedConnectionIds(): Set<string> {
        return new Set(this.fFlowComponent.getSelection().fConnectionIds);
    }

    private suppressReassignOfNeighbours(grab: ConnectionEndGrab | null): void {
        const suppressed = new Set<string>();
        if (grab) {
            const portId = grab.endpoint === 'source' ? grab.connection.sourcePortId : grab.connection.targetPortId;
            this.connectionsAtPort(portId)
                .filter((conn) => conn.id !== grab.connection.id)
                .forEach((conn) => suppressed.add(conn.id));
        }

        if (suppressed.size === 0 && this.reassignSuppressedConnectionIds().size === 0) {
            return;
        }

        this.reassignSuppressedConnectionIds.set(suppressed);
        // Foblex picks the connection to reassign later in this same mousedown, so the disabled flags must reach it synchronously.
        this.cd.detectChanges();
    }

    private connectionsAtPort(portId: string): ConnectionModel[] {
        return this.flowService
            .connections()
            .filter((conn) => conn.sourcePortId === portId || conn.targetPortId === portId);
    }

    private findConnectionElement(connectionId: string): Element | null {
        return this.hostElement.nativeElement.querySelector(`f-connection[id="${CSS.escape(connectionId)}"]`);
    }

    private getDragHandle(connectionElement: Element, endpoint: 'source' | 'target'): Element | null {
        return connectionElement.querySelector(
            endpoint === 'source' ? 'circle[f-connection-drag-handle-start]' : 'circle[f-connection-drag-handle-end]'
        );
    }

    public onReassignConnection(event: FReassignConnectionEvent): void {
        const existingConnection = this.flowService.connections().find((conn) => conn.id === event.connectionId);

        if (!existingConnection) {
            console.warn('Connection not found for reassignment:', event.connectionId);
            return;
        }

        const groupIds = new Set(
            this.reassignGroupIds.includes(existingConnection.id) ? this.reassignGroupIds : [existingConnection.id]
        );
        this.reassignGroupIds = [];

        const isSourceMoved = event.endpoint === 'source';
        const nextPortId = (isSourceMoved ? event.nextSourceId : event.nextTargetId) as CustomPortId | undefined;
        const currentPortId = isSourceMoved ? existingConnection.sourcePortId : existingConnection.targetPortId;
        if (!nextPortId || nextPortId === currentPortId) {
            return;
        }

        const connections = this.flowService.connections();
        const moved = connections.filter((conn) => groupIds.has(conn.id));
        const updated: ConnectionModel[] = [];
        const occupied = connections.filter((conn) => !groupIds.has(conn.id));

        for (const conn of moved) {
            const sourcePortId = isSourceMoved ? nextPortId : conn.sourcePortId;
            const targetPortId = isSourceMoved ? conn.targetPortId : nextPortId;
            const error = this.getReassignError(sourcePortId, targetPortId, [...occupied, ...updated]);
            if (error) {
                this.toastService.warning(error, 5000, 'bottom-right');
                return;
            }
            updated.push(
                createFlowConnection(sourcePortId.split('_')[0], targetPortId.split('_')[0], sourcePortId, targetPortId)
            );
        }

        this.hasUnarrangedChanges.set(true);
        this.undoRedoService.stateChanged();

        moved.forEach((conn) => this.flowService.removeConnection(conn.id));
        updated.forEach((conn) => this.flowService.addConnection(conn));

        this.toastService.success(
            updated.length > 1 ? `${updated.length} connections reassigned` : 'Connection reassigned successfully',
            3000,
            'bottom-right'
        );
    }

    private getReassignError(
        sourcePortId: CustomPortId,
        targetPortId: CustomPortId,
        connections: ConnectionModel[]
    ): string | null {
        if (!isConnectionValid(sourcePortId, targetPortId)) {
            return 'Cannot reassign connection: Invalid port combination';
        }
        if (connections.some((conn) => conn.sourcePortId === sourcePortId && conn.targetPortId === targetPortId)) {
            return 'These ports are already connected';
        }
        if (this.hasOccupiedPort(sourcePortId, targetPortId, connections)) {
            return 'This port already has a connection';
        }
        return null;
    }

    private hasOccupiedPort(sourcePortId: string, targetPortId: string, connections: ConnectionModel[]): boolean {
        const allPorts = this.flowService.nodes().flatMap((n) => n.ports ?? []);
        const sourcePort = allPorts.find((p) => p.id === sourcePortId);
        const targetPort = allPorts.find((p) => p.id === targetPortId);
        const sourceOccupied =
            !!sourcePort && !sourcePort.multiple && connections.some((conn) => conn.sourcePortId === sourcePortId);
        const targetOccupied =
            !!targetPort && !targetPort.multiple && connections.some((conn) => conn.targetPortId === targetPortId);
        return sourceOccupied || targetOccupied;
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

        if (this.hasOccupiedPort(pair.sourcePortId, pair.targetPortId, currentConnections)) {
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

    /** Allowed in read-only mode too: copying reads the flow, and the preview hands the copy to the live editor. */
    public onCopy(): void {
        if (this.isDialogOpen()) {
            return;
        }

        const previousClipboard = this.clipboardService.getClipboardData();
        const selections: ICurrentSelection = this.fFlowComponent.getSelection();
        this.clipboardService.copy(selections);
        if (this.clipboardService.getClipboardData() !== previousClipboard) {
            this.copied.emit();
        }
    }

    public onPaste(): void {
        if (this.isReadOnly) {
            this.notifyReadOnly();
            return;
        }
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
            this.rerouteSegmentConnections();
            this.fFlowComponent.select(newNodeIds, newConnectionIds);
            this.cd.detectChanges();
            this.fFlowComponent?.redraw();
        }, 0);
    }

    public onUndo(): void {
        if (this.isReadOnly) {
            this.notifyReadOnly();
            return;
        }
        if (this.isEditingLocked()) {
            return;
        }

        this.hasUnarrangedChanges.set(true);
        this.undoRedoService.onUndo();
        this.rerouteSegmentConnections();
    }

    public onRedo(): void {
        if (this.isReadOnly) {
            this.notifyReadOnly();
            return;
        }
        if (this.isEditingLocked()) {
            return;
        }

        this.hasUnarrangedChanges.set(true);
        this.undoRedoService.onRedo();
        this.rerouteSegmentConnections();
    }

    /** Keyboard edits in the version preview would otherwise do nothing without a word. */
    private notifyReadOnly(): void {
        this.toastService.info('Preview mode is read-only. Exit preview to edit the flow', 3000, 'bottom-right');
    }

    protected onUndoRedoPerformed(): void {
        this.hasUnarrangedChanges.set(true);
        this.rerouteSegmentConnections();
    }

    public onDelete(): void {
        if (this.isReadOnly) {
            this.notifyReadOnly();
            return;
        }
        this.hasUnarrangedChanges.set(true);
        if (this.isEditingLocked()) {
            return;
        }

        const selections: ICurrentSelection = this.fFlowComponent.getSelection();
        this.deleteSelections(selections);
    }

    public onDeleteNode(node: NodeModel): void {
        if (this.isEditingLocked()) {
            return;
        }
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

        if (this.isEditingLocked()) {
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
            this.flowService.updateConnectionWaypoints(connectionId, waypoints, true);
            return;
        }

        const normalizedWaypoints = this.normalizeWaypointsForConnection(connection, waypoints);

        const isSameElements =
            normalizedWaypoints.length === waypoints.length && normalizedWaypoints.every((p, i) => p === waypoints[i]);

        this.flowService.updateConnectionWaypoints(
            connectionId,
            isSameElements ? waypoints : normalizedWaypoints,
            normalizedWaypoints.length > 0
        );
    }

    public onNodeDroppedFromPanel(event: FCreateNodeEvent): void {
        if (this.isReadOnly) {
            return;
        }
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

        setTimeout(() => {
            this.rerouteSegmentConnections();
            this.cd.detectChanges();
            this.fFlowComponent?.redraw();
        }, 0);
    }

    public onContextMenu(event: MouseEvent): void {
        event.preventDefault();
        if (this.isReadOnly) {
            return;
        }
        this.contextMenuPosition.set({ x: event.clientX, y: event.clientY });
        this.showContextMenu.set(true);
    }

    public onCloseContextMenu(): void {
        this.showContextMenu.set(false);
    }

    public onAddNodeFromContextMenu(event: CreateNodeRequest): void {
        this.showContextMenu.set(false);

        if (this.isReadOnly || this.isDialogOpen()) {
            return;
        }

        if (event.type === NodeType.END && this.flowService.hasEndNode()) {
            this.toastService.warning('Only one End node is allowed', 4000, 'bottom-right');
            return;
        }

        this.hasUnarrangedChanges.set(true);
        this.undoRedoService.stateChanged();

        const position = this.fFlowComponent.getPositionInFlow(
            PointExtensions.initialize(this.contextMenuPosition().x, this.contextMenuPosition().y)
        );
        const newNode = this.nodeFactory.createNode(event.type, { ...event.overrides, position });
        const safePosition = this.findNearestFreePosition(
            { x: this.snapToGrid(position.x), y: this.snapToGrid(position.y) },
            this.getCollisionBounds(newNode),
            this.flowService.nodes()
        );
        this.flowService.addNode({ ...newNode, position: safePosition });

        setTimeout(() => {
            this.rerouteSegmentConnections();
            this.cd.detectChanges();
            this.fFlowComponent?.redraw();
        }, 0);
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
            if (this.isReadOnly) {
                return;
            }
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
                    readOnly: this.isReadOnly,
                } satisfies DomainDialogData,
            });

            dialogRef.closed.subscribe((result: unknown) => {
                if (this.isReadOnly) return;
                if (result !== null && typeof result === 'object' && result !== undefined) {
                    this.updateStartNodeInitialState(result as Record<string, unknown>);
                }
            });
        } else {
            void this.sidePanelService.trySelectNode(node);
        }
    }

    public onNodePanelSaved(updatedNode: NodeModel): void {
        if (this.isReadOnly) {
            return;
        }
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
        if (this.isReadOnly) {
            return;
        }
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

    public commitSidePanelToFlow(): boolean {
        if (!this.nodePanelShell?.hasPanelInstance()) {
            return true;
        }
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
            return false;
        }
        // Skip the writeback if the captured node was removed from the flow
        // (e.g. during DT→CDT conversion the old panel instance lingers briefly
        //  before the outlet swaps to the newly-selected node's panel).
        if (this.flowService.nodes().some((n) => n.id === updatedNode.id)) {
            this.flowService.updateNode(updatedNode);
        }
        return true;
    }

    public emitSave(): void {
        if (this.isReadOnly) return;
        if (!this.commitSidePanelToFlow()) return;
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

        const dragData = event.fData as { fNodeIds?: string[]; fConnectionId?: string } | undefined;
        if (dragData?.fConnectionId && dragData.fConnectionId === this.reassignGroupIds[0]) {
            this.reassignFollowerIds.set(new Set(this.reassignGroupIds.slice(1)));
        }
        if (dragData?.fNodeIds) {
            dragData.fNodeIds.forEach((id: string) => this.draggingElements.add(id));
        }

        // Panning also starts a drag; in read-only nothing can change, so there is no state to record.
        if (!this.isReadOnly) {
            this.undoRedoService.stateChanged();
        }
    }

    private rerouteSegmentConnections(): void {
        const nodes = this.flowService.nodes();
        const connections = this.flowService.connections();
        const backwardIds = this.backwardConnectionIds();

        for (const conn of connections) {
            const wasBackward = this.previousBackwardConnectionIds.has(conn.id);
            const isBackward = backwardIds.has(conn.id);
            const changedFromBackwardToForward = wasBackward && !isBackward;
            const changedFromForwardToBackward = !wasBackward && isBackward;
            const classificationFlipped = changedFromBackwardToForward || changedFromForwardToBackward;
            const wasFrozen = this.frozenConnectionIds().has(conn.id);

            if (isBackward) {
                if (wasFrozen && !classificationFlipped) continue;

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
                    this.flowService.updateConnectionWaypoints(conn.id, [newWaypoint], wasFrozen ? false : undefined);
                    this.bumpConnectionRenderVersion(conn.id);
                }

                continue;
            }

            if (wasFrozen && !classificationFlipped) continue;

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
                        this.flowService.updateConnectionWaypoints(
                            currentConnection.id,
                            normalizedRestore,
                            wasFrozen ? false : undefined
                        );
                        this.bumpConnectionRenderVersion(currentConnection.id);
                    }
                } else if (changedFromBackwardToForward && (currentConnection.waypoints?.length ?? 0) > 0) {
                    this.flowService.updateConnectionWaypoints(currentConnection.id, [], wasFrozen ? false : undefined);
                    this.bumpConnectionRenderVersion(currentConnection.id);
                }

                continue;
            }

            let clearedStaleFlipWaypoint = false;

            for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
                const waypoints = computeSegmentAvoidanceWaypoints(
                    current,
                    nodes,
                    changedFromBackwardToForward ? undefined : current.waypoints
                );

                if (waypoints === null) {
                    if (
                        changedFromBackwardToForward &&
                        !clearedStaleFlipWaypoint &&
                        (current.waypoints?.length ?? 0) > 0
                    ) {
                        this.flowService.updateConnectionWaypoints(current.id, [], wasFrozen ? false : undefined);
                        this.bumpConnectionRenderVersion(current.id);
                    }
                    break;
                }

                const normalizedWaypoints = this.normalizeWaypointsForConnection(current, waypoints);
                if (waypointsEqual(current.waypoints ?? [], normalizedWaypoints)) break;

                this.flowService.updateConnectionWaypoints(
                    current.id,
                    normalizedWaypoints,
                    wasFrozen ? false : undefined
                );
                this.bumpConnectionRenderVersion(current.id);
                current = { ...current, waypoints: normalizedWaypoints };
                clearedStaleFlipWaypoint = true;
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
            data: { readOnly: this.isReadOnly } satisfies FlowSettingsPanelData,
        });
    }

    public updateMouseTrackerPosition(event: IPoint): void {
        this.mouseCursorPosition = event;
    }

    public onAutoArrange(): void {
        if (this._arrangingLock || this.isReadOnly) return;
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
        const backwardConns = connections.filter((c) => backwardIds.has(c.id) && !c.userAdjustedWaypoints);

        // Clear ALL non-user-adjusted waypoints (including backward) so every connection
        // starts from a clean state. Backward arcs are re-computed each frame below.
        for (const conn of connections) {
            if (conn.waypoints?.length && !conn.userAdjustedWaypoints) {
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
                        if (!bwIds.has(conn.id) || conn.userAdjustedWaypoints) continue;
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
                readOnly: this.isReadOnly,
            } satisfies DomainDialogData,
        });

        dialogRef.closed.subscribe((result: unknown) => {
            if (this.isReadOnly) return;
            if (result !== null && typeof result === 'object' && result !== undefined) {
                this.updateStartNodeInitialState(result as Record<string, unknown>);
            }
        });
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

    protected resetReassignHighlight(): void {
        if (this.reassignSuppressedConnectionIds().size > 0) {
            this.reassignSuppressedConnectionIds.set(new Set<string>());
        }
        if (this.reassignFollowerIds().size > 0) {
            this.reassignFollowerIds.set(new Set<string>());
        }
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
        if (!this.currentFlowId || this.isReadOnly) return;
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
            schedule_trigger_node_list: [],
            edge_list: [],
            knowledge_node_list: [],
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
                case NodeType.SCHEDULE_TRIGGER:
                    body.schedule_trigger_node_list.push(id);
                    break;
                case NodeType.KNOWLEDGE_RETRIEVER:
                    body.knowledge_node_list.push(id);
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
        this.rerouteSegmentConnections();
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

    // Editing is locked while a dialog is open, a full graph save is in flight, or the editor is read-only.
    // (Saving lock fixes edits made mid-save being discarded when the response is applied.)
    private isEditingLocked(): boolean {
        return this.isDialogOpen() || this.isSaving || this.isReadOnly;
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

    // Same as Foblex's own position/scale inputs: the whole offset goes into `position`.
    private applyViewport(viewport: FlowViewport): void {
        const transform = this.fCanvasComponent.transform;
        transform.position = { ...viewport.position };
        transform.scaledPosition = PointExtensions.initialize();
        transform.scale = viewport.scale;
        this.fCanvasComponent.redraw();
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

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
