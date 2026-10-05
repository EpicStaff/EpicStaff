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
    input,
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
import { GetGraphLightRequest } from '../../features/flows/models/graph.model';
import { ToastService } from '../../services/notifications';
import { DomainDialogComponent } from '../components/domain-dialog/domain-dialog.component';
import { FlowActionPanelComponent } from '../components/flow-action-panel/flow-action-panel.component';
import { FlowBaseNodeComponent } from '../components/flow-base-node/flow-base-node.component';
import { FlowNodeVariablesOverlayComponent } from '../components/flow-base-node/flow-node-variables-overlay.component';
import { FlowExportImportButtonComponent } from '../components/flow-export-import-button/flow-export-import-button.component';
import { FlowFilesButtonComponent } from '../components/flow-files-button/flow-files-button.component';
import { FlowGraphContextMenuComponent } from '../components/flow-graph-context-menu/flow-graph-context-menu.component';
import { FlowSettingsPanelComponent } from '../components/flow-settings-panel/flow-settings-panel.component';
import { FlowShortcutsButtonComponent } from '../components/flow-shortcuts-button/flow-shortcuts-button.component';
import { CdtExportImportService } from '../components/node-panels/classification-decision-table-node-panel/cdt-export-import.service';
import { NodePanelShellComponent } from '../components/node-panels/node-panel-shell/node-panel-shell.component';
import { NodesSearchComponent } from '../components/nodes-search/nodes-search.component';
import { NoteEditDialogComponent } from '../components/note-edit-dialog/note-edit-dialog.component';
import { MouseTrackerDirective } from '../core/directives/mouse-tracker.directive';
import { ShortcutListenerDirective } from '../core/directives/shortcut-listener.directive';
import { WaypointTooltipDirective } from '../core/directives/waypoint-tooltip.directive';
import { getPortPosition } from '../core/geometry/port-position';
import { computeRowSnapY } from '../core/helpers/cdt-row-snap.util';
import { getMinimapClassForNode } from '../core/helpers/get-minimap-class.util';
import { defineSourceTargetPair, isBackwardConnection, isConnectionValid } from '../core/helpers/helpers';
import {
    CollisionBounds,
    findNearestFreePosition,
    getCollisionBounds,
    getExactBounds,
    GRID_CELL_SIZE,
    hasCollision,
    resolveOverlapsForNode,
    snapPointToGrid,
} from '../core/helpers/node-placement.utils';
import { normalizeTableNodeSize } from '../core/helpers/node-size.util';
import { computeLayout } from '../core/layout/compute-layout';
import { ConnectionModel } from '../core/models/connection.model';
import { FlowModel } from '../core/models/flow.model';
import { FlowViewport } from '../core/models/flow-viewport.model';
import { GraphNoteModel, NodeModel, StartNodeModel } from '../core/models/node.model';
import { CreateNodeRequest } from '../core/models/node-creation.types';
import { CustomPortId } from '../core/models/port.model';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { OrthogonalPathBuilder } from '../core/routing/orthogonal.path-builder';
import { normalizeOrthogonalWaypoints } from '../core/routing/orthogonal-route-shapes';
import { resolveWireEnds, routeAll } from '../core/routing/route-all';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { FlowReadOnlyService } from '../services/flow-readonly.service';
import { FlowSettingsService } from '../services/flow-settings.service';
import { KeyValueEntryDraftsService } from '../services/key-value-entry-drafts.service';
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
            useFactory: () => ({ orthogonal: new OrthogonalPathBuilder() }),
        },
        KeyValueEntryDraftsService,
    ],
    imports: [
        FFlowModule,
        FZoomDirective,
        FormsModule,
        FlowBaseNodeComponent,
        FlowNodeVariablesOverlayComponent,
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
    public readonly availableFlows = input<GetGraphLightRequest[]>([]);
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
    readonly extractToSubflow = output<Set<string>>();
    readonly unpackSubflow = output<string>();

    @ViewChild(FFlowComponent, { static: false })
    private fFlowComponent!: FFlowComponent;

    @ViewChild(FCanvasComponent, { static: true })
    private fCanvasComponent!: FCanvasComponent;

    @ViewChild(FZoomDirective, { static: true })
    private fZoomDirective!: FZoomDirective;

    @ViewChild('nodePanelShell', { static: false })
    private nodePanelShell?: NodePanelShellComponent;

    @ViewChild('arrangeBtnRef') private arrangeBtnRef?: ElementRef<HTMLButtonElement>;

    @ViewChild('ioOverlayLayer', { static: true })
    private ioOverlayLayerRef?: ElementRef<HTMLDivElement>;

    private nodesContainerEl: Element | null = null;
    private overlayNodesObserver: MutationObserver | null = null;

    @ViewChild(NodesSearchComponent) private nodesSearchComponent?: NodesSearchComponent;

    public closeNodesSearch(): void {
        this.nodesSearchComponent?.closeSearch();
    }

    readonly GRID_CELL_SIZE = GRID_CELL_SIZE;
    private readonly MIN_HORIZONTAL_NODE_GAP = GRID_CELL_SIZE;
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
    protected readonly extractableSelectedNodeIds = computed<Set<string>>(() => {
        const nodes = this.flowService.nodes();
        return new Set(
            this.selectedNodeIds().filter((id) => {
                const type = nodes.find((n) => n.id === id)?.type;
                return type !== NodeType.START && type !== NodeType.END;
            })
        );
    });

    readonly multiSelectTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        this.multiSelectActive() || (event instanceof MouseEvent && (event.shiftKey || event.ctrlKey || event.metaKey));

    readonly selectionAreaTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        this.multiSelectActive() || (event instanceof MouseEvent && event.shiftKey);

    readonly canvasMoveTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        !this.multiSelectActive() && !(event instanceof MouseEvent && event.shiftKey);

    /** Gates every Foblex gesture that edits the graph (move, resize, rotate, connect, reassign, waypoints). */
    readonly editGestureTrigger = (): boolean => !this.flowReadOnly.isReadOnly();

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
    // Connection id → backward at the last reroute. An id missing here has no classification to flip from.
    private readonly previousBackwardClassification = new Map<string, boolean>();
    private draggedNodeIds = new Set<string>();
    private draggingElements = new Set<string>();
    private isDragging = false;
    protected readonly connectionRenderVersions = signal<Record<string, number>>({});
    private readonly hiddenConnectionIds = signal<Set<string>>(new Set<string>());
    protected readonly reassignSuppressedConnectionIds = signal<ReadonlySet<string>>(new Set<string>());
    protected readonly reassignFollowerIds = signal<ReadonlySet<string>>(new Set<string>());
    private reassignGroupIds: string[] = [];

    /** Version preview: read-only (via flowReadOnly), and import/export and files are hidden. */
    protected readonly isPreview = inject(FLOW_EDITOR_PREVIEW);
    protected readonly flowService = inject(FlowService);
    protected readonly sidePanelService = inject(SidePanelService);
    protected readonly flowReadOnly = inject(FlowReadOnlyService);
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

        // `f-canvas` uses selective content projection and drops any element that
        // doesn't match one of its slots, so the overlay layer is rendered outside
        // `<f-flow>` and moved in here once the canvas's internal containers exist.
        afterNextRender(
            () => {
                this.moveOverlayLayerIntoCanvas();
                this.setupOverlayTransformSync();
            },
            { injector: this.injector }
        );
    }

    private moveOverlayLayerIntoCanvas(): void {
        const layer = this.ioOverlayLayerRef?.nativeElement;
        const canvas = this.hostElement.nativeElement.querySelector('f-canvas');
        const nodesContainer = canvas?.querySelector('.f-nodes-container');
        if (!layer || !canvas || !nodesContainer) return;

        canvas.insertBefore(layer, nodesContainer);
        this.nodesContainerEl = nodesContainer;
    }

    // foblex rewrites a dragged node's inline `transform` continuously; mirroring it onto
    // the matching overlay (instead of binding the overlay to `node.position`) is the only
    // way the overlay tracks the node mid-drag rather than jumping on drop.
    private setupOverlayTransformSync(): void {
        const nodesContainer = this.nodesContainerEl;
        if (!nodesContainer) return;

        this.overlayNodesObserver = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                if (mutation.type === 'attributes' && mutation.target instanceof HTMLElement) {
                    this.syncOverlayTransform(mutation.target);
                } else if (mutation.type === 'childList') {
                    this.syncAllOverlayTransforms();
                }
            }
        });
        this.overlayNodesObserver.observe(nodesContainer, {
            attributes: true,
            attributeFilter: ['style'],
            subtree: true,
            childList: true,
        });

        this.syncAllOverlayTransforms();
    }

    private syncOverlayTransform(nodeEl: HTMLElement): void {
        const layer = this.ioOverlayLayerRef?.nativeElement;
        const nodeId = nodeEl.getAttribute('data-f-node-id');
        if (!layer || !nodeId) return;

        const overlayEl = layer.querySelector<HTMLElement>(`[data-overlay-node-id="${nodeId}"]`);
        if (!overlayEl) return;

        overlayEl.style.transform = nodeEl.style.transform;
    }

    private syncAllOverlayTransforms(): void {
        const nodesContainer = this.nodesContainerEl;
        if (!nodesContainer) return;

        nodesContainer
            .querySelectorAll<HTMLElement>('[data-f-node-id]')
            .forEach((nodeEl) => this.syncOverlayTransform(nodeEl));
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
        this.overlayNodesObserver?.disconnect();
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
        this.rerouteSegmentConnections();

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
        this.rerouteSegmentConnections();
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
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
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
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
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
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }
        if (this.isEditingLocked()) {
            return;
        }

        this.hasUnarrangedChanges.set(true);
        this.undoRedoService.onRedo();
        this.rerouteSegmentConnections();
    }

    protected onUndoRedoPerformed(): void {
        this.hasUnarrangedChanges.set(true);
        this.rerouteSegmentConnections();
    }

    public onDelete(): void {
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
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

    public onUnpackSubflow(node: NodeModel): void {
        this.unpackSubflow.emit(node.id);
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

        // A candidate insert starts a drag: Foblex keeps moving the point inside this very array, so
        // it is stored as is (the 'orthogonal' builder draws it normalized meanwhile).
        const existingCount = connection.waypoints?.length ?? 0;
        if (waypoints.length > existingCount) {
            this.flowService.updateConnectionWaypoints(connectionId, waypoints, true);
            return;
        }

        const nodesById = new Map(this.flowService.nodes().map((node) => [node.id, node]));
        const ends = resolveWireEnds(connection, nodesById);
        const normalizedWaypoints = ends
            ? normalizeOrthogonalWaypoints(
                  getPortPosition(ends.sourceNode, ends.sourcePort),
                  waypoints,
                  getPortPosition(ends.targetNode, ends.targetPort)
              )
            : waypoints;
        // A right-click that removes a bend the orthogonal shape can't do without (normalizing puts it
        // straight back) resets the wire to automatic routing, as removing the last point does.
        const isResetToRouter =
            normalizedWaypoints.length === 0 ||
            (waypoints.length < existingCount && waypointsEqual(normalizedWaypoints, connection.waypoints ?? []));
        this.flowService.updateConnectionWaypoints(
            connectionId,
            isResetToRouter ? [] : normalizedWaypoints,
            !isResetToRouter
        );

        // The other wires make room for the edited one (it now occupies its corridor); a reset wire
        // is the router's again.
        this.rerouteSegmentConnections();
    }

    public onNodeDroppedFromPanel(event: FCreateNodeEvent): void {
        if (this.flowReadOnly.isReadOnly()) {
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
        if (this.flowReadOnly.isReadOnly()) return;
        this.contextMenuPosition.set({ x: event.clientX, y: event.clientY });
        this.showContextMenu.set(true);
    }

    public onCloseContextMenu(): void {
        this.showContextMenu.set(false);
    }

    public onAddNodeFromContextMenu(event: CreateNodeRequest): void {
        this.showContextMenu.set(false);

        if (this.flowReadOnly.isReadOnly() || this.isDialogOpen()) {
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
            if (this.flowReadOnly.isReadOnly()) {
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
                },
                // This editor's injector: the dialog then sees this editor's read-only state.
                injector: this.injector,
            });

            dialogRef.closed.subscribe((result: unknown) => {
                if (this.flowReadOnly.isReadOnly()) return;
                if (result !== null && typeof result === 'object' && result !== undefined) {
                    this.updateStartNodeInitialState(result as Record<string, unknown>);
                }
            });
        } else {
            void this.sidePanelService.trySelectNode(node);
        }
    }

    public onNodePanelSaved(updatedNode: NodeModel): void {
        if (this.flowReadOnly.isReadOnly()) {
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
        if (this.flowReadOnly.isReadOnly()) {
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
        if (this.flowReadOnly.isReadOnly()) return;
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
        this.rerouteSegmentConnections();
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
        if (!this.flowReadOnly.isReadOnly()) {
            this.undoRedoService.stateChanged();
        }

        // Router waypoints go stale as soon as a node moves: drop them on the dragged nodes' wires so
        // the 'orthogonal' builder's fallback follows the drag live. Drag end routes them again.
        const staleConnections = this.flowService
            .connections()
            .filter(
                (conn) =>
                    !conn.userAdjustedWaypoints &&
                    !!conn.waypoints?.length &&
                    (this.draggingElements.has(conn.sourceNodeId) || this.draggingElements.has(conn.targetNodeId))
            );
        if (staleConnections.length > 0) {
            staleConnections.forEach((conn) => this.flowService.updateConnectionWaypoints(conn.id, []));
            // Foblex redraws from the waypoints input on the next pointer move; it must be [] by then.
            this.cd.detectChanges();
        }
    }

    private rerouteSegmentConnections(): void {
        const backwardIds = this.backwardConnectionIds();

        // A hand-edited wire whose backward/forward classification flipped no longer fits its
        // points: un-freeze it so the router takes it over below. A wire seen for the first time
        // (just loaded or added) has not flipped.
        for (const conn of this.flowService.connections()) {
            const previousBackward = this.previousBackwardClassification.get(conn.id);
            const classificationFlipped =
                previousBackward !== undefined && previousBackward !== backwardIds.has(conn.id);
            if (conn.userAdjustedWaypoints && classificationFlipped) {
                this.flowService.updateConnectionWaypoints(conn.id, [], false);
                this.bumpConnectionRenderVersion(conn.id);
            }
        }

        const connections = this.flowService.connections();
        const routes = routeAll(this.flowService.nodes(), connections);
        for (const conn of connections) {
            const points = routes.get(conn.id);
            if (points && !waypointsEqual(conn.waypoints ?? [], points)) {
                this.flowService.updateConnectionWaypoints(conn.id, points);
                this.bumpConnectionRenderVersion(conn.id);
            }
        }

        this.previousBackwardClassification.clear();
        for (const conn of connections) {
            this.previousBackwardClassification.set(conn.id, backwardIds.has(conn.id));
        }
    }

    public onDragEnded(): void {
        const autoAlignedNodeIds = new Set<string>();

        for (const id of this.draggedNodeIds) {
            const currentNodes = this.flowService.nodes();
            const current = currentNodes.find((n) => n.id === id);
            if (!current) continue;

            const otherNodes = currentNodes.filter((n) => n.id !== id);

            // Part 1: exact bounds vertically; horizontally padded by MIN_HORIZONTAL_NODE_GAP so a
            // connection arrow always has room. Node creation/paste are unaffected — they still
            // go through getCollisionBounds() elsewhere.
            const draggedBounds = this.getHorizontallyPaddedBounds(current);
            let resolvedPosition = findNearestFreePosition(current.position, draggedBounds, otherNodes, getExactBounds);

            // Part 2: magnetic snap to a connected Decision Table (plain or Classification) row.
            // Only the y axis is ever touched, and only within the snap threshold; a snap that
            // would reintroduce an overlap is discarded in favor of the resolved drop position.
            const snappedY = computeRowSnapY(current, resolvedPosition, currentNodes, this.flowService.connections());
            if (snappedY !== null) {
                const snappedPosition = { x: resolvedPosition.x, y: snappedY };
                if (!hasCollision(snappedPosition, draggedBounds, otherNodes, getExactBounds)) {
                    resolvedPosition = snappedPosition;
                }
            }

            if (resolvedPosition.x !== current.position.x || resolvedPosition.y !== current.position.y) {
                this.flowService.updateNode({ ...current, position: resolvedPosition });
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

    private getHorizontallyPaddedBounds(node: NodeModel): CollisionBounds {
        const bounds = getExactBounds(node);
        return {
            ...bounds,
            width: bounds.width + 2 * this.MIN_HORIZONTAL_NODE_GAP,
            offsetX: bounds.offsetX - this.MIN_HORIZONTAL_NODE_GAP,
        };
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
            injector: this.injector,
        });
    }

    public updateMouseTrackerPosition(event: IPoint): void {
        this.mouseCursorPosition = event;
    }

    public onAutoArrange(): void {
        if (this._arrangingLock || this.flowReadOnly.isReadOnly()) return;
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
        const newPositions = computeLayout(nodes, connections);

        const alreadyArranged = nodes.every((n) => {
            const target = newPositions.get(n.id);
            return !target || (n.position.x === target.x && n.position.y === target.y);
        });
        // Arranging starts the wires over too: hand-edited points refer to the old node positions.
        const hasHandEditedWires = connections.some((conn) => conn.userAdjustedWaypoints);
        if (alreadyArranged && !hasHandEditedWires) {
            this.hasUnarrangedChanges.set(false);
            this._arrangingLock = false;
            this.isArranging.set(false);
            return;
        }

        this.undoRedoService.stateChanged();

        const startPositions = new Map(nodes.map((n) => [n.id, { ...n.position }]));

        // Clear ALL waypoints, hand-edited ones included, so every connection draws the builder's
        // fallback during the animation. The router runs once the nodes have landed.
        for (const conn of connections) {
            if (conn.waypoints?.length || conn.userAdjustedWaypoints) {
                this.flowService.updateConnectionWaypoints(conn.id, [], false);
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

            this.flowService.updateNodesInBatch(updatedNodes);
            this.cd.detectChanges();
            this.fFlowComponent?.redraw();

            if (t < 1) {
                this.arrangeAnimationId = requestAnimationFrame(frame);
            } else {
                this.arrangeAnimationId = null;
                setTimeout(() => {
                    this.rerouteSegmentConnections();
                    this.cd.detectChanges();
                    this.fFlowComponent?.redraw();
                    // Every node moved: bring the whole arranged flow into view.
                    this.fCanvasComponent.fitToScreen({ x: 200, y: 100 }, true);
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
            injector: this.injector,
        });

        dialogRef.closed.subscribe((result: unknown) => {
            if (this.flowReadOnly.isReadOnly()) return;
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

    protected onExtractToSubflow(): void {
        const ids = this.extractableSelectedNodeIds();
        if (ids.size === 0) return;
        this.extractToSubflow.emit(ids);
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
        if (this.flowReadOnly.isReadOnly()) return;
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
            key_value_node_list: [],
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
                case NodeType.KEY_VALUE:
                    body.key_value_node_list.push(id);
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
        // A loaded flow starts a new history: its saved hand-edited wires must not count as flipped.
        this.previousBackwardClassification.clear();
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
        return this.isDialogOpen() || this.isSaving || this.flowReadOnly.isReadOnly();
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
        this.rerouteSegmentConnections();

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
