import { Dialog } from '@angular/cdk/dialog';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    EventEmitter,
    inject,
    Injector,
    Input,
    input,
    NgZone,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    output,
    signal,
    SimpleChanges,
    untracked,
    ViewChild,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
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
import { AppSvgIconComponent, AuthorshipDetailsSource } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, NodeType, ResourceCode, ShortcutParams } from '@shared/models';
import { fromEvent, Subject } from 'rxjs';

import { GetGraphLightRequest } from '../../features/flows/models/graph.model';
import { ToastService } from '../../services/notifications';
import { DomainDialogComponent, DomainDialogData } from '../components/domain-dialog/domain-dialog.component';
import { FlowActionPanelComponent } from '../components/flow-action-panel/flow-action-panel.component';
import { FlowBaseNodeComponent } from '../components/flow-base-node/flow-base-node.component';
import { FlowNodeVariablesOverlayComponent } from '../components/flow-base-node/flow-node-variables-overlay.component';
import { FlowExportImportButtonComponent } from '../components/flow-export-import-button/flow-export-import-button.component';
import { FlowFilesButtonComponent } from '../components/flow-files-button/flow-files-button.component';
import { FlowGraphContextMenuComponent } from '../components/flow-graph-context-menu/flow-graph-context-menu.component';
import { FlowSettingsPanelComponent } from '../components/flow-settings-panel/flow-settings-panel.component';
import { FlowShortcutsButtonComponent } from '../components/flow-shortcuts-button/flow-shortcuts-button.component';
import { CDT_ROUTE_CONTINUE_COPY } from '../components/node-panels/classification-decision-table-node-panel/cdt.constants';
import { NodePanelShellComponent } from '../components/node-panels/node-panel-shell/node-panel-shell.component';
import { NodesSearchComponent } from '../components/nodes-search/nodes-search.component';
import { NoteEditDialogComponent, NoteEditDialogData } from '../components/note-edit-dialog/note-edit-dialog.component';
import { MouseTrackerDirective } from '../core/directives/mouse-tracker.directive';
import { WaypointTooltipDirective } from '../core/directives/waypoint-tooltip.directive';
import { computeRowSnapY } from '../core/helpers/cdt-row-snap.util';
import { buildInsertionConnections, findConnectionUnderNode } from '../core/helpers/drop-on-connection.util';
import { getMinimapClassForNode } from '../core/helpers/get-minimap-class.util';
import { defineSourceTargetPair, isConnectionValid } from '../core/helpers/helpers';
import { computeHoverContext, HoverContext } from '../core/helpers/hover-context.util';
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
import { subgraphFlowOptions, subgraphNodeRequest } from '../core/helpers/subgraph-flows.util';
import { CanvasPan, EDITOR_ACTIONS } from '../core/keymap/editor-actions';
import { flowIdOf } from '../core/keymap/shortcut-params';
import { FlowModel } from '../core/models/flow.model';
import { FlowViewport } from '../core/models/flow-viewport.model';
import { GraphNoteModel, NodeModel, StartNodeModel } from '../core/models/node.model';
import { CreateNodeRequest } from '../core/models/node-creation.types';
import { CustomPortId } from '../core/models/port.model';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { CurvedPathBuilder } from '../core/routing/curved.path-builder';
import { OrthogonalPathBuilder } from '../core/routing/orthogonal.path-builder';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { FlowReadOnlyService, TRIGGER_NODES_NEED_USE_MESSAGE } from '../services/flow-readonly.service';
import { FlowSettingsService } from '../services/flow-settings.service';
import { KeyValueEntryDraftsService } from '../services/key-value-entry-drafts.service';
import { KeymapService } from '../services/keymap.service';
import { NodeAuthorshipStore } from '../services/node-authorship.store';
import { NodeFactoryService } from '../services/node-factory.service';
import { SidePanelService } from '../services/side-panel.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { createFlowConnection } from '../utils/connection.factory';
import { normalizeFlowPorts } from '../utils/load';
import { FlowArrangeAnimatorService } from './flow-arrange-animator.service';
import { FlowImportExportService } from './flow-import-export-handler.service';
import { FlowReassignHandlerService, ReassignHandlerCallbacks } from './flow-reassign-handler.service';
import { FlowRoutingOrchestratorService } from './flow-routing-orchestrator.service';
import { FlowSelectionManagerService } from './flow-selection-manager.service';

/** How long a refused reassignment — and the same refusal when drawing a connection — stays on screen. */
const CONNECTION_REFUSED_TOAST_MS = 5000;

const CANVAS_PAN_STEP_PX = 40;

const CANVAS_PAN_FAST_STEP_PX = 200;

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
            useValue: {
                orthogonal: new OrthogonalPathBuilder(),
                'adaptive-curve': new CurvedPathBuilder(),
            },
        },
        KeyValueEntryDraftsService,
        FlowArrangeAnimatorService,
        FlowImportExportService,
        FlowReassignHandlerService,
        FlowRoutingOrchestratorService,
        FlowSelectionManagerService,
    ],
    imports: [
        FFlowModule,
        FZoomDirective,
        FormsModule,
        FlowBaseNodeComponent,
        FlowNodeVariablesOverlayComponent,
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

    @ViewChild('ioOverlayLayer', { static: true })
    private ioOverlayLayerRef?: ElementRef<HTMLDivElement>;

    private nodesContainerEl: Element | null = null;
    private overlayNodesObserver: MutationObserver | null = null;

    @ViewChild(NodesSearchComponent) private nodesSearchComponent?: NodesSearchComponent;
    private readonly shortcutsAnchor = viewChild.required<ElementRef<HTMLElement>>('shortcutsAnchor');
    private readonly flowHost = viewChild.required('flowHost', { read: ElementRef<HTMLElement> });

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
    private lastPointer: IPoint | null = null;
    protected isLoaded = signal(false);
    protected showContextMenu = signal(false);
    private readonly arrangeAnimator = inject(FlowArrangeAnimatorService);
    protected readonly hasUnarrangedChanges = this.arrangeAnimator.hasUnarrangedChanges;
    protected readonly isArranging = this.arrangeAnimator.isArranging;
    protected readonly flowSettings = inject(FlowSettingsService);
    public smartRoutingEnabled = signal<boolean>(false);
    protected readonly hoveredConnectionId = signal<string | null>(null);
    public hoveredNodeId = signal<string | null>(null);

    public readonly selectionManager = inject(FlowSelectionManagerService);

    /** Gates every Foblex gesture that edits the graph (move, resize, rotate, connect, reassign, waypoints). */
    readonly editGestureTrigger = (): boolean => !this.flowReadOnly.isReadOnly();

    protected readonly isAutoArrangeDisabled = computed(
        () =>
            this.isArranging() ||
            this.flowService.nodes().length - this.arrangeAnimator.pinnedNodeIds().size < 2 ||
            !this.hasUnarrangedChanges()
    );

    protected readonly nodeColorMap = computed<Map<string, string>>(() => {
        const map = new Map<string, string>();
        for (const node of this.flowService.nodes()) {
            map.set(node.id, node.color);
        }
        return map;
    });

    protected readonly sortedConnections = computed(() => {
        const backwardIds = this.routingOrchestrator.backwardConnectionIds();
        const hiddenIds = this.hiddenConnectionIds();
        const hoveredId = this.hoveredConnectionId();
        const selectedIds = this.selectionManager.selectedConnectionIds();

        const connections = [...this.flowService.visibleConnections()].filter(
            (connection) => !hiddenIds.has(connection.id)
        );

        return connections.sort((a, b) => {
            // Hovered connection on top of everything
            const aHovered = a.id === hoveredId ? 1 : 0;
            const bHovered = b.id === hoveredId ? 1 : 0;
            if (aHovered !== bHovered) return aHovered - bHovered;

            // Selected above normal
            const aRaised = selectedIds.has(a.id) ? 1 : 0;
            const bRaised = selectedIds.has(b.id) ? 1 : 0;
            if (aRaised !== bRaised) return aRaised - bRaised;

            const aBackward = backwardIds.has(a.id) ? 1 : 0;
            const bBackward = backwardIds.has(b.id) ? 1 : 0;
            return aBackward - bBackward;
        });
    });

    protected readonly hoverContext = computed<HoverContext | null>(() => {
        const nodeId = this.hoveredNodeId();
        if (!nodeId) return null;
        return computeHoverContext(nodeId, this.flowService.nodes(), this.flowService.connections());
    });

    /** The node may not be changed here, so it cannot be dragged either (a trigger node without Flows:Use). */
    public isNodeReadOnly(node: NodeModel): boolean {
        return this.flowReadOnly.isNodeTypeReadOnly(node.type);
    }

    public getNodeZIndex(node: NodeModel): number {
        if (this.hoveredNodeId() === node.id) return 1000;
        return Math.max(2, 500 - Math.floor(Math.max(0, node.position?.y ?? 0) / 10));
    }

    private readonly destroy$ = new Subject<void>();
    private draggedNodeIds = new Set<string>();
    private draggingElements = new Set<string>();
    private isDragging = false;
    private readonly hiddenConnectionIds = signal<Set<string>>(new Set<string>());
    protected readonly reassignHandler = inject(FlowReassignHandlerService);

    /** Version preview: read-only (via flowReadOnly), and import/export and files are hidden. */
    protected readonly isPreview = inject(FLOW_EDITOR_PREVIEW);
    protected readonly flowService = inject(FlowService);
    protected readonly routingOrchestrator = inject(FlowRoutingOrchestratorService);
    protected readonly sidePanelService = inject(SidePanelService);
    protected readonly flowReadOnly = inject(FlowReadOnlyService);
    private readonly undoRedoService = inject(UndoRedoService);
    private readonly clipboardService = inject(ClipboardService);
    private readonly nodeFactory = inject(NodeFactoryService);
    private readonly cd = inject(ChangeDetectorRef);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly importExportHandler = inject(FlowImportExportService);
    /** The flow page's store in the live editor, the preview's own (empty) one in a version preview. */
    private readonly nodeAuthorshipStore = inject(NodeAuthorshipStore);
    private readonly injector = inject(Injector);
    private readonly hostElement = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly keymap = inject(KeymapService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly ngZone = inject(NgZone);

    // Start from the current count so a canvas re-created after an earlier save request
    // (e.g. when leaving version preview) does not replay it. untracked: this initialiser runs
    // while the parent template is rendering and must not subscribe that view to the signal.
    private lastSeenFullSaveRequest = untracked(() => this.sidePanelService.fullSaveRequest());

    constructor() {
        this.registerShortcuts();

        effect(() => {
            const requestCount = this.sidePanelService.fullSaveRequest();
            if (requestCount > this.lastSeenFullSaveRequest) {
                this.lastSeenFullSaveRequest = requestCount;
                this.emitSave();
            }
        });

        effect(() => {
            this.flowSettings.edgeStyle(); // track the signal
            untracked(() => this.routingOrchestrator.rerouteSegmentConnections());
        });

        // `f-canvas` uses selective content projection and drops any element that
        // doesn't match one of its slots, so the overlay layer is rendered outside
        // `<f-flow>` and moved in here once the canvas's internal containers exist.
        afterNextRender(
            () => {
                this.moveOverlayLayerIntoCanvas();
                this.setupOverlayTransformSync();
                this.trackPointerOverCanvas();
            },
            { injector: this.injector }
        );
    }

    private registerShortcuts(): void {
        const options = { destroyRef: this.destroyRef };
        this.keymap.register('editing.copy', () => this.onCopy(), options);
        this.keymap.register('editing.paste', () => this.onPaste(), options);
        this.keymap.register('editing.delete', () => this.onDelete(), options);
        this.keymap.register('editing.undo', () => this.onUndo(), options);
        this.keymap.register('editing.redo', () => this.onRedo(), options);
        this.keymap.register('editing.escape', () => this.onEscapeKey(), { ...options, allowInEditable: true });
        this.keymap.register(
            'navigating.shortcuts',
            () => this.onOpenShortcuts(this.shortcutsAnchor().nativeElement),
            options
        );
        for (const action of EDITOR_ACTIONS) {
            if ('nodeType' in action && !('param' in action)) {
                const request: CreateNodeRequest = { type: action.nodeType };
                this.keymap.register(action.id, () => this.onNodeShortcut(request), options);
            }
        }
        this.keymap.register('node.subgraph', (_event, { params }) => this.onSubgraphShortcut(params), options);
        for (const action of EDITOR_ACTIONS) {
            if ('pan' in action) {
                const pan = action.pan;
                this.keymap.register(action.id, () => this.onPanShortcut(pan), {
                    ...options,
                    runOutsideAngular: true,
                    when: (event) => this.isCanvasKeyTarget(event.target),
                });
            }
        }
    }

    private isCanvasKeyTarget(target: EventTarget | null): boolean {
        if (!(target instanceof Node)) {
            return false;
        }
        return target === target.ownerDocument?.body || this.flowHost().nativeElement.contains(target);
    }

    private onPanShortcut(pan: CanvasPan): void {
        const canvas = this.fCanvasComponent;
        if (!canvas || this.isDialogOpen() || this.showContextMenu()) {
            return;
        }
        const step = pan.fast ? CANVAS_PAN_FAST_STEP_PX : CANVAS_PAN_STEP_PX;
        const position = canvas.getPosition();
        canvas.transform.position = PointExtensions.initialize(position.x - pan.x * step, position.y - pan.y * step);
        canvas.redraw();
        canvas.emitCanvasChangeEvent();
    }

    private onSubgraphShortcut(params: ShortcutParams | null): void {
        const flowId = flowIdOf(params);
        const flow = subgraphFlowOptions(this.availableFlows(), this.currentFlowId).find(
            (candidate) => candidate.id === flowId
        );
        if (flow) {
            this.onNodeShortcut(subgraphNodeRequest(flow));
        }
    }

    private onNodeShortcut(request: CreateNodeRequest): void {
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }
        if (this.isEditingLocked() || this.showContextMenu()) {
            return;
        }
        this.addNodeAt(request, this.lastPointer);
    }

    private trackPointerOverCanvas(): void {
        const host = this.flowHost().nativeElement;
        this.ngZone.runOutsideAngular(() => {
            fromEvent<PointerEvent>(host, 'pointermove')
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((event) => {
                    const overMinimap = event.target instanceof Element && event.target.closest('f-minimap') !== null;
                    this.lastPointer = overMinimap ? null : { x: event.clientX, y: event.clientY };
                });
            fromEvent(host, 'pointerleave')
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(() => (this.lastPointer = null));
        });
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
            this.openNodePanel(this.initialNodeId);
        }
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['flowState'] && !changes['flowState'].firstChange) {
            const stateToApply = this.importExportHandler.processImportedFlowState(this.flowState);
            this.applyIncomingFlowState(stateToApply);
            if (this.importExportHandler.fitAfterNextFlowChange) {
                this.importExportHandler.fitAfterNextFlowChange = false;
                setTimeout(() => {
                    this.fCanvasComponent.fitToScreen({ x: 200, y: 100 }, false);
                }, 0);
            }
        }
        if (changes['initialNodeId'] && changes['initialNodeId'].currentValue) {
            this.openNodePanel(changes['initialNodeId'].currentValue);
        }
        if (changes['isSaving'] && changes['isSaving'].currentValue === true) {
            this.onCloseContextMenu();
        }
    }

    public ngOnDestroy(): void {
        this.arrangeAnimator.cancelAnimation();
        this.overlayNodesObserver?.disconnect();
        this.destroy$.next();
        this.destroy$.complete();
    }

    public onInitialized(): void {
        this.isLoaded.set(true);
        setTimeout(() => {
            this.routingOrchestrator.rerouteSegmentConnections();
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

    private readonly reassignCallbacks: ReassignHandlerCallbacks = {
        detectChanges: () => this.cd.detectChanges(),
        queryConnectionElement: (connectionId) =>
            this.hostElement.nativeElement.querySelector(`f-connection[id="${CSS.escape(connectionId)}"]`),
    };

    public onFlowMouseDown(event: MouseEvent): void {
        const isLocked = event.shiftKey || this.selectionManager.multiSelectActive() || this.isEditingLocked();
        this.reassignHandler.handleMouseDown(event, isLocked, this.fFlowComponent, this.reassignCallbacks);
    }

    public onReassignConnection(event: FReassignConnectionEvent): void {
        if (this.reassignHandler.onReassignConnection(event)) {
            this.arrangeAnimator.markUnarranged();
        }
    }

    public onConnectionAdded(event: FCreateConnectionEvent): void {
        this.arrangeAnimator.markUnarranged();
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

        if (this.reassignHandler.hasOccupiedPort(pair.sourcePortId, pair.targetPortId, currentConnections)) {
            this.toastService.warning('This port already has a connection', 4000, 'bottom-right');
            return;
        }

        if (this.reassignHandler.isRoutePortBlocked(pair.sourcePortId)) {
            this.toastService.warning(
                CDT_ROUTE_CONTINUE_COPY.routePortBlockedByContinue,
                CONNECTION_REFUSED_TOAST_MS,
                'bottom-right'
            );
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
        this.routingOrchestrator.rerouteSegmentConnections();
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
        this.arrangeAnimator.markUnarranged();
        if (this.isEditingLocked()) {
            return;
        }

        const pastePosition = this.mouseCursorPosition
            ? snapPointToGrid(this.toFlowPosition(this.mouseCursorPosition))
            : { x: 0, y: 0 };

        const canPaste = (node: NodeModel): boolean => !this.flowReadOnly.isNodeTypeReadOnly(node.type);
        // Recorded before the paste changes the flow, and only when it will change it.
        if (this.clipboardService.getClipboardData()?.nodes.some(canPaste)) {
            this.undoRedoService.stateChanged();
        }
        const { newNodes, newConnections, skippedNodeCount } = this.clipboardService.paste(pastePosition, canPaste);
        if (skippedNodeCount > 0) {
            this.toastService.warning(
                `${skippedNodeCount} trigger node${skippedNodeCount > 1 ? 's were' : ' was'} not pasted. ${TRIGGER_NODES_NEED_USE_MESSAGE}`,
                6000,
                'bottom-right'
            );
        }
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
            this.routingOrchestrator.rerouteSegmentConnections();
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

        this.arrangeAnimator.markUnarranged();
        this.undoRedoService.onUndo();
        this.routingOrchestrator.rerouteSegmentConnections();
    }

    public onRedo(): void {
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }
        if (this.isEditingLocked()) {
            return;
        }

        this.arrangeAnimator.markUnarranged();
        this.undoRedoService.onRedo();
        this.routingOrchestrator.rerouteSegmentConnections();
    }

    protected onUndoRedoPerformed(): void {
        this.arrangeAnimator.markUnarranged();
        this.routingOrchestrator.rerouteSegmentConnections();
    }

    public onDelete(): void {
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }
        this.arrangeAnimator.markUnarranged();
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
        this.arrangeAnimator.markUnarranged();
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
        this.arrangeAnimator.markUnarranged();
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
        this.routingOrchestrator.onWaypointsChanged(connectionId, waypoints);
    }

    public onNodeDroppedFromPanel(event: FCreateNodeEvent): void {
        if (this.flowReadOnly.isReadOnly()) {
            return;
        }
        this.arrangeAnimator.markUnarranged();
        if (!event.data || typeof event.data !== 'object') {
            return;
        }
        if (this.flowReadOnly.isNodeTypeReadOnly((event.data as NodeModel).type)) {
            this.flowReadOnly.notifyNodeTypeBlocked((event.data as NodeModel).type);
            return;
        }

        const normalizedNode = normalizeTableNodeSize(event.data as NodeModel);

        const updatedNode: NodeModel = {
            ...normalizedNode,
            position: findNearestFreePosition(
                {
                    x: this.snapToGrid(event.rect.x),
                    y: this.snapToGrid(event.rect.y),
                },
                getCollisionBounds(normalizedNode),
                this.flowService.nodes()
            ),
        };
        this.flowService.updateNode(updatedNode);

        setTimeout(() => {
            this.routingOrchestrator.rerouteSegmentConnections();
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

        this.addNodeAt(event, this.contextMenuPosition());
    }

    public onOpenNodePanel(node: NodeModel): void {
        if (this.selectionManager.multiSelectActive()) {
            const current = this.fFlowComponent.getSelection();
            const alreadySelected = current.fNodeIds.includes(node.id);
            const newNodeIds = alreadySelected
                ? current.fNodeIds.filter((id) => id !== node.id)
                : [...current.fNodeIds, node.id];
            this.selectionManager.selectedNodeIds.set(newNodeIds);
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

            const data: NoteEditDialogData = {
                node: noteNode,
                authorship: this.nodeAuthorshipStore.authorshipOf(noteNode),
            };
            const dialogRef = this.dialog.open(NoteEditDialogComponent, { data, disableClose: true });

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
            const data: DomainDialogData = {
                initialData: startNode.data?.initialState || {},
                authorship: this.nodeAuthorshipStore.authorshipOf(startNode),
            };

            const dialogRef = this.dialog.open(DomainDialogComponent, {
                disableClose: true,
                width: '1000px',
                height: '800px',
                maxWidth: '90vw',
                maxHeight: '90vh',
                panelClass: 'domain-dialog-panel',
                backdropClass: 'domain-dialog-backdrop',
                data,
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
        this.applyNodePanelUpdate(updatedNode, true);
    }

    public onNodePanelAutosaved(updatedNode: NodeModel): void {
        this.applyNodePanelUpdate(updatedNode, false);
    }

    public commitSidePanelToFlow(): boolean {
        // A panel that may not change its node (a trigger node without Flows:Use) has nothing to commit.
        if (!this.nodePanelShell?.hasPanelInstance() || this.nodePanelShell.isNodeReadOnly()) {
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
        if (this.isNodeReadOnly(node)) {
            this.revertNodeLayout(node);
            return;
        }
        this.undoRedoService.stateChanged();

        const updatedNode = {
            ...node,
            size: {
                width: event.width,
                height: event.height,
            },
        };

        this.flowService.updateNode(updatedNode);
        this.routingOrchestrator.rerouteSegmentConnections();
    }

    public onDragStarted(event: FDragStartedEvent): void {
        this.isDragging = true;
        this.draggingElements.clear();

        const dragData = event.fData as { fNodeIds?: string[]; fConnectionId?: string } | undefined;
        this.reassignHandler.recordDragStart(dragData?.fConnectionId);
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

    public onDragEnded(): void {
        if (this.draggedNodeIds.size === 1 && !this.flowReadOnly.isReadOnly()) {
            const draggedNodeId = [...this.draggedNodeIds][0];
            const connections = this.flowService.connections();
            const isUnconnected = !connections.some(
                (conn) => conn.sourceNodeId === draggedNodeId || conn.targetNodeId === draggedNodeId
            );
            if (isUnconnected) {
                const nodes = this.flowService.nodes();
                const node = nodes.find((n) => n.id === draggedNodeId);
                if (node && node.type !== NodeType.NOTE) {
                    const nodesById = new Map(nodes.map((n) => [n.id, n]));
                    const hit = findConnectionUnderNode(node, connections, nodesById);
                    if (hit) {
                        const result = buildInsertionConnections(node, hit);
                        if (result) {
                            this.flowService.removeConnection(result.connectionToRemove.id);
                            this.flowService.addConnection(result.newConnections[0]);
                            this.flowService.addConnection(result.newConnections[1]);
                        }
                    }
                }
            }
        }

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
                this.routingOrchestrator.rerouteSegmentConnections();
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
        // Dragging is disabled on such a node, but a drag of a selection still carries it along.
        if (this.isNodeReadOnly(node)) {
            this.revertNodeLayout(node);
            this.flowReadOnly.notifyNodeTypeBlocked(node.type);
            return;
        }
        this.arrangeAnimator.markUnarranged();
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
        this.arrangeAnimator.autoArrange({
            detectChanges: () => this.cd.detectChanges(),
            redraw: () => this.fFlowComponent?.redraw(),
            fitToScreen: (padding, animate) => this.fCanvasComponent.fitToScreen(padding, animate),
        });
    }

    public onDomainClick(): void {
        const data: DomainDialogData = {
            initialData: this.flowService.startNodeInitialState(),
            authorship: this.startNodeAuthorship(),
        };

        const dialogRef = this.dialog.open(DomainDialogComponent, {
            width: '1000px',
            height: '800px',
            maxWidth: '90vw',
            maxHeight: '90vh',
            panelClass: 'domain-dialog-panel',
            backdropClass: 'domain-dialog-backdrop',
            data,
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
        this.selectionManager.recordPointerDown(event);
    }

    public onFlowPointerUp(event: PointerEvent): void {
        this.selectionManager.recordPointerUp(event);
    }

    protected resetReassignHighlight(): void {
        this.reassignHandler.resetHighlight();
    }

    public onFlowClick(event: MouseEvent): void {
        this.showContextMenu.set(false);
        const wasMultiSelect = this.selectionManager.multiSelectActive();
        this.selectionManager.handleFlowClick(event, this.isDragging);
        if (wasMultiSelect && !this.selectionManager.multiSelectActive()) {
            this.fFlowComponent.select([], []);
        }
    }

    public onEscapeKey(): void {
        if (this.selectionManager.escapeSelection()) {
            this.fFlowComponent.select([], []);
        }
    }

    public onToggleMultiSelect(): void {
        const wasActive = this.selectionManager.multiSelectActive();
        this.selectionManager.toggleMultiSelect();
        if (wasActive) {
            this.fFlowComponent.select([], []);
        }
    }

    public onSelectionChange(event: { nodeIds: string[] }): void {
        this.selectionManager.handleSelectionChange(event, this.mouseCursorPosition, {
            getPositionInFlow: (point) =>
                this.fFlowComponent.getPositionInFlow(PointExtensions.initialize(point.x, point.y)),
            selectInFlow: (nodeIds, connectionIds) => this.fFlowComponent.select(nodeIds, connectionIds),
            getSelectedConnectionIds: () => new Set(this.fFlowComponent.getSelection().fConnectionIds),
        });
    }

    protected onExtractToSubflow(): void {
        const ids = this.selectionManager.extractableSelectedNodeIds();
        if (ids.size === 0) return;
        // Extracting creates the nodes again in the new subflow.
        const readOnlyNode = this.flowService
            .nodes()
            .find((node) => ids.has(node.id) && this.flowReadOnly.isNodeTypeReadOnly(node.type));
        if (readOnlyNode) {
            this.flowReadOnly.notifyNodeTypeBlocked(readOnlyNode.type);
            return;
        }
        this.extractToSubflow.emit(ids);
    }

    public onExportSelectedAsJson(): void {
        this.importExportHandler.onExportSelectedAsJson(this.currentFlowId);
    }

    public onExportSelectedAsCsv(): void {
        this.importExportHandler.onExportSelectedAsCsv();
    }

    public onExportAllAsJson(): void {
        this.importExportHandler.onExportAllAsJson(this.currentFlowId);
    }

    public onImportNodes(): void {
        this.importExportHandler.onImportNodes(
            this.currentFlowId,
            this.hasUnsavedChanges,
            this.flowReadOnly.isReadOnly(),
            () => this.importComplete.emit()
        );
    }

    public onOpenShortcuts(anchorEl: HTMLElement): void {
        this.openShortcuts.emit(anchorEl.getBoundingClientRect());
    }

    private applyIncomingFlowState(flowState: FlowModel): void {
        const normalizedFlowState = normalizeFlowPorts(flowState);
        this.flowService.setFlow(normalizedFlowState);
        // A loaded flow starts a new history: its saved hand-edited wires must not count as flipped.
        this.routingOrchestrator.clearBackwardClassification();
        this.routingOrchestrator.rerouteSegmentConnections();
    }

    private addNodeAt(request: CreateNodeRequest, clientPoint: IPoint | null): void {
        if (this.flowReadOnly.isNodeTypeReadOnly(request.type)) {
            this.flowReadOnly.notifyNodeTypeBlocked(request.type);
            return;
        }

        if (request.type === NodeType.END && this.flowService.hasEndNode()) {
            this.toastService.warning('Only one End node is allowed', 4000, 'bottom-right');
            return;
        }

        this.arrangeAnimator.markUnarranged();
        this.undoRedoService.stateChanged();

        const screenPoint = clientPoint ?? this.canvasCenter();
        const position = this.fFlowComponent.getPositionInFlow(
            PointExtensions.initialize(screenPoint.x, screenPoint.y)
        );
        const newNode = this.nodeFactory.createNode(request.type, { ...request.overrides, position });
        const safePosition = findNearestFreePosition(
            { x: this.snapToGrid(position.x), y: this.snapToGrid(position.y) },
            getCollisionBounds(newNode),
            this.flowService.nodes()
        );
        this.flowService.addNode({ ...newNode, position: safePosition });

        setTimeout(() => {
            this.routingOrchestrator.rerouteSegmentConnections();
            this.cd.detectChanges();
            this.fFlowComponent?.redraw();
        }, 0);
    }

    private canvasCenter(): IPoint {
        const rect = this.flowHost().nativeElement.getBoundingClientRect();
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
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

    /** The toolbar's Domain window edits the Start node's variables, so its footer credits the Start node. */
    private startNodeAuthorship(): AuthorshipDetailsSource {
        const startNode = this.flowService.nodes().find((node) => node.type === NodeType.START);
        // No Start node: nobody to credit, shown as dashes like a node that is not saved yet.
        return this.nodeAuthorshipStore.authorshipOf(startNode ?? { type: NodeType.START, backendId: null });
    }

    public openNodePanel(nodeId: string): void {
        this.sidePanelService.setSelectedNodeId(nodeId);
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
        this.routingOrchestrator.rerouteSegmentConnections();

        if (selections.fNodeIds.length > 0) {
            this.selectionManager.clearSelection();
            this.fFlowComponent.select([], []);
        }
    }

    private applyNodePanelUpdate(updatedNode: NodeModel, clearSelection: boolean): void {
        if (this.flowReadOnly.isNodeTypeReadOnly(updatedNode.type)) {
            return;
        }
        const normalizedNode = normalizeTableNodeSize(updatedNode);
        this.flowService.updateNode(normalizedNode);
        const movedNodeIds = this.resolveTableOverlaps(normalizedNode);

        if (clearSelection) {
            this.sidePanelService.clearSelection();
        }

        setTimeout(() => {
            this.routingOrchestrator.rerouteSegmentConnections();

            const affectedNodeIds = new Set<string>([normalizedNode.id, ...movedNodeIds]);

            for (const conn of this.flowService.connections()) {
                if (affectedNodeIds.has(conn.sourceNodeId) || affectedNodeIds.has(conn.targetNodeId)) {
                    this.routingOrchestrator.bumpConnectionRenderVersion(conn.id);
                }
            }

            this.cd.detectChanges();
        }, 0);
    }

    private resolveTableOverlaps(node: NodeModel): string[] {
        if (node.type !== NodeType.TABLE) {
            return [];
        }

        // A node this user may not change stays where it is, even if the table now overlaps it.
        const movedNodes = resolveOverlapsForNode(node.id, this.flowService.nodes()).filter(
            (movedNode) => !this.isNodeReadOnly(movedNode)
        );

        if (movedNodes.length > 0) {
            this.flowService.updateNodesInBatch(movedNodes);
        }

        return movedNodes.map((movedNode) => movedNode.id);
    }

    private snapToGrid(value: number): number {
        return Math.round(value / this.GRID_CELL_SIZE) * this.GRID_CELL_SIZE;
    }

    /**
     * Puts a node Foblex moved or resized back where the flow has it: new position and size objects
     * make Foblex take them again, while the flow's values stay as they were.
     */
    private revertNodeLayout(node: NodeModel): void {
        const current = this.flowService.nodes().find((candidate) => candidate.id === node.id);
        if (!current) return;
        this.flowService.updateNode({ ...current, position: { ...current.position }, size: { ...current.size } });
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
            this.routingOrchestrator.rerouteSegmentConnections();
            this.cd.detectChanges();
            this.fFlowComponent?.redraw();
            return;
        }

        this.hiddenConnectionIds.set(new Set(affectedConnectionIds));
        this.cd.detectChanges();
        this.fFlowComponent?.redraw();

        requestAnimationFrame(() => {
            this.routingOrchestrator.rerouteSegmentConnections();

            for (const connectionId of affectedConnectionIds) {
                this.routingOrchestrator.bumpConnectionRenderVersion(connectionId);
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
