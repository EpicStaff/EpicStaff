import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    NgZone,
    OnInit,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CheckboxComponent,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SliderWithStepperComponent,
    ToggleSwitchComponent,
} from '@shared/components';
import { ResizableSidebarDirective } from '@shared/directives';
import { SidebarWidthService } from '@shared/services';
import { catchError, debounceTime, distinctUntilChanged, EMPTY, of, Subject, switchMap, tap } from 'rxjs';

import {
    GRAPH_NOT_INDEXED_MESSAGE,
    GRAPH_SEARCH_DEBOUNCE_MS,
    GRAPH_SEARCH_MAX_LENGTH,
    GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES,
    GRAPH_VISUALIZATION_DETAIL_PANEL_WIDTH_KEY,
    GRAPH_VISUALIZATION_DETAIL_PANEL_WIDTH_OPTIONS,
    GRAPH_VISUALIZATION_MIN_ENTITIES,
    GRAPH_VISUALIZATION_SIDEBAR_WIDTH_KEY,
    GRAPH_VISUALIZATION_SIDEBAR_WIDTH_OPTIONS,
} from '../../constants/constants';
import { isGraphNotIndexedError } from '../../helpers/graph-not-indexed-error.util';
import { GraphVisualizationData, VisualizationEntity } from '../../models/graph-visualization.model';
import { GraphRagService } from '../../services/graph-rag.service';
import {
    DRAG_REHEAT_ALPHA,
    INITIAL_LAYOUT_SPREAD,
    SIMULATION_CHARGE_STRENGTH,
    SIMULATION_LINK_DISTANCE,
} from './graph-scene.constants';
import { GraphEdge, GraphNode } from './graph-scene.model';
import { GraphSceneService } from './graph-scene.service';

/**
 * - `no-matches`: the request succeeded but returned no entities (search with no hits, or an empty graph).
 * - `not-indexed`: the backend answered 409 `graph_not_indexed` — the graph exists but has not been indexed yet.
 */
type ViewState = 'loading' | 'ready' | 'no-matches' | 'not-indexed' | 'error';

interface EntityTypeFilter {
    type: string | null;
    label: string;
    checked: boolean;
    color: string;
}

interface SimulationNode {
    index: number;
    x: number;
    y: number;
    z?: number;
    fx?: number | null;
    fy?: number | null;
    fz?: number | null;
}

@Component({
    selector: 'app-graph-rag-visualization',
    templateUrl: './graph-rag-visualization.component.html',
    styleUrls: ['./graph-rag-visualization.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ButtonComponent,
        CheckboxComponent,
        FetchErrorStateComponent,
        FormsModule,
        LoadingSpinnerComponent,
        ResizableSidebarDirective,
        SearchComponent,
        SliderWithStepperComponent,
        ToggleSwitchComponent,
        AppSvgIconComponent,
    ],
    providers: [GraphSceneService],
})
export class GraphRagVisualizationComponent implements OnInit {
    // 1. Inputs
    readonly ragId = input.required<number>();

    // 2. ViewChild
    private readonly graphCanvas = viewChild<ElementRef<HTMLCanvasElement>>('graphCanvas');
    private readonly canvasContainer = viewChild<ElementRef<HTMLElement>>('canvasContainer');

    // 3. Signals & Computed
    readonly viewState = signal<ViewState>('loading');
    readonly errorMessage = signal('');
    readonly is3D = signal(false);
    readonly maxEntities = signal(GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES);
    readonly searchTerm = signal('');
    readonly labelsVisible = signal(false);
    readonly selectedNodeIndex = signal<number | null>(null);
    readonly selectedEdgeIndex = signal<number | null>(null);
    readonly hoveredNodeTitle = signal<string | null>(null);
    readonly hoverPosition = signal<{ x: number; y: number }>({ x: 0, y: 0 });

    readonly toolbarVisible = signal(false);
    readonly entityCount = signal(0);
    readonly totalEntityCount = signal(0);
    readonly relationshipCount = signal(0);

    /** Never below the current value, so the control cannot clamp what is already displayed. */
    readonly sliderMax = computed(() =>
        Math.max(this.totalEntityCount(), this.maxEntities(), GRAPH_VISUALIZATION_MIN_ENTITIES)
    );
    readonly sliderStep = computed(() => {
        const total = this.totalEntityCount();
        if (total <= 10) return 1;
        if (total <= 50) return 5;
        if (total <= 100) return 10;
        return 100;
    });
    readonly entityTypeFilters = signal<EntityTypeFilter[]>([]);

    readonly selectedNode = computed<GraphNode | null>(() => {
        const index = this.selectedNodeIndex();
        if (index === null) return null;
        const nodes = this.sceneService.getNodes();
        return nodes[index] ?? null;
    });

    readonly connectedEdges = computed<Array<{ edge: GraphEdge; otherNode: GraphNode }>>(() => {
        const node = this.selectedNode();
        if (!node) return [];
        const edges = this.sceneService.getEdges();
        const nodes = this.sceneService.getNodes();
        const result: Array<{ edge: GraphEdge; otherNode: GraphNode }> = [];
        for (const edge of edges) {
            if (edge.sourceIndex === node.index) {
                result.push({ edge, otherNode: nodes[edge.targetIndex] });
            } else if (edge.targetIndex === node.index) {
                result.push({ edge, otherNode: nodes[edge.sourceIndex] });
            }
        }
        return result;
    });

    readonly selectedEdge = computed<GraphEdge | null>(() => {
        const index = this.selectedEdgeIndex();
        if (index === null) return null;
        return this.sceneService.getEdges()[index] ?? null;
    });

    readonly selectedEdgeNodes = computed<{ source: GraphNode; target: GraphNode } | null>(() => {
        const edge = this.selectedEdge();
        if (!edge) return null;
        const nodes = this.sceneService.getNodes();
        return { source: nodes[edge.sourceIndex], target: nodes[edge.targetIndex] };
    });

    readonly nodeDescription = signal<string | null>(null);
    readonly edgeDescription = signal<string | null>(null);
    readonly detailLoading = signal(false);

    readonly detailPanelOpen = computed(() => this.selectedNode() !== null || this.selectedEdge() !== null);
    /** The sidebar stays mounted across reloads; its filters only apply to a drawn graph. */
    readonly typeFiltersDisabled = computed(() => this.viewState() !== 'ready');

    // 4. Effects
    /**
     * Keeps the 3D scene bound to the canvas element: creates it once the canvas exists and graph
     * data is loaded, and disposes it as soon as that canvas leaves the DOM.
     */
    private readonly canvasEffect = effect(() => {
        const canvas = this.graphCanvas()?.nativeElement ?? null;
        const container = this.canvasContainer()?.nativeElement ?? null;
        untracked(() => {
            if (this.sceneCanvas !== null && this.sceneCanvas !== canvas) {
                this.teardownScene();
            }
            if (canvas && container && this.sceneCanvas === null && this.sceneService.getNodes().length > 0) {
                void this.initializeScene(canvas, container);
            }
        });
    });

    /**
     * Hover picking runs on every pointer move, so the listener lives outside the Angular zone and
     * re-enters it only when the hovered node's tooltip actually changes.
     */
    private readonly pointerMoveEffect = effect((onCleanup) => {
        const canvas = this.graphCanvas()?.nativeElement;
        if (!canvas) return;
        const listener = (event: PointerEvent): void => this.handleCanvasPointerMove(event);
        this.ngZone.runOutsideAngular(() => canvas.addEventListener('pointermove', listener));
        onCleanup(() => canvas.removeEventListener('pointermove', listener));
    });

    private readonly nodeDetailTrigger$ = new Subject<GraphNode | null>();
    private readonly edgeDetailTrigger$ = new Subject<GraphEdge | null>();

    /** Fetch entity description lazily when a node is selected. */
    private readonly nodeDetailEffect = effect(() => {
        this.nodeDetailTrigger$.next(this.selectedNode());
    });

    /** Fetch relationship description lazily when an edge is selected. */
    private readonly edgeDetailEffect = effect(() => {
        this.edgeDetailTrigger$.next(this.selectedEdge());
    });

    // 5. Sidebar
    private readonly sidebarWidthService = inject(SidebarWidthService);
    readonly sidebarWidth = this.sidebarWidthService.getWidth(
        GRAPH_VISUALIZATION_SIDEBAR_WIDTH_KEY,
        GRAPH_VISUALIZATION_SIDEBAR_WIDTH_OPTIONS
    );
    readonly detailPanelWidth = this.sidebarWidthService.getWidth(
        GRAPH_VISUALIZATION_DETAIL_PANEL_WIDTH_KEY,
        GRAPH_VISUALIZATION_DETAIL_PANEL_WIDTH_OPTIONS
    );
    protected readonly sidebarWidthKey = GRAPH_VISUALIZATION_SIDEBAR_WIDTH_KEY;
    protected readonly sidebarWidthOptions = GRAPH_VISUALIZATION_SIDEBAR_WIDTH_OPTIONS;
    protected readonly detailPanelWidthKey = GRAPH_VISUALIZATION_DETAIL_PANEL_WIDTH_KEY;
    protected readonly detailPanelWidthOptions = GRAPH_VISUALIZATION_DETAIL_PANEL_WIDTH_OPTIONS;

    protected readonly searchMaxLength = GRAPH_SEARCH_MAX_LENGTH;
    protected readonly minEntities = GRAPH_VISUALIZATION_MIN_ENTITIES;

    // 6. Private fields
    private readonly graphRagService = inject(GraphRagService);
    private readonly sceneService = inject(GraphSceneService);
    private readonly ngZone = inject(NgZone);

    private simulation: { stop: () => void; reheat: () => void } | null = null;
    private simNodes: SimulationNode[] = [];
    /** Canvas the scene is (being) created for; null when no scene exists. */
    private sceneCanvas: HTMLCanvasElement | null = null;
    /** Bumped on every scene (re)creation and teardown, so a stale async initialization gives up. */
    private sceneGeneration = 0;
    /** Bumped on every simulation start and teardown, so only the latest start creates a simulation. */
    private simulationGeneration = 0;
    private destroyed = false;
    private readonly loadTrigger$ = new Subject<{ ragId: number; maxEntities: number; search?: string }>();
    private readonly searchTrigger$ = new Subject<string>();
    private draggedNodeIndex: number | null = null;
    private isDragging = false;
    private clickedEdgeOnDown = -1;

    constructor() {
        inject(DestroyRef).onDestroy(() => {
            this.destroyed = true;
            this.teardownScene();
        });

        this.loadTrigger$
            .pipe(
                switchMap(({ ragId, maxEntities, search }) =>
                    this.graphRagService.getVisualizationData(ragId, maxEntities, search).pipe(
                        tap((data) => this.handleDataLoaded(data)),
                        catchError((error: HttpErrorResponse) => {
                            this.handleError(error);
                            return EMPTY;
                        })
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe();

        this.searchTrigger$
            .pipe(debounceTime(GRAPH_SEARCH_DEBOUNCE_MS), distinctUntilChanged(), takeUntilDestroyed())
            .subscribe(() => {
                this.entityTypeFilters.set([]);
                this.closeDetailPanel();
                this.loadData();
            });

        this.nodeDetailTrigger$
            .pipe(
                switchMap((node) => {
                    this.nodeDescription.set(null);
                    if (!node) return of(null);
                    this.detailLoading.set(true);
                    return this.graphRagService.getEntityDetails(this.ragId(), node.id).pipe(
                        tap((result) => {
                            this.nodeDescription.set(result.description);
                            this.detailLoading.set(false);
                        }),
                        catchError(() => {
                            this.detailLoading.set(false);
                            return of(null);
                        })
                    );
                }),
                takeUntilDestroyed()
            )
            .subscribe();

        this.edgeDetailTrigger$
            .pipe(
                switchMap((edge) => {
                    this.edgeDescription.set(null);
                    if (!edge) return of(null);
                    this.detailLoading.set(true);
                    return this.graphRagService.getRelationshipDetails(this.ragId(), edge.id).pipe(
                        tap((result) => {
                            this.edgeDescription.set(result.description);
                            this.detailLoading.set(false);
                        }),
                        catchError(() => {
                            this.detailLoading.set(false);
                            return of(null);
                        })
                    );
                }),
                takeUntilDestroyed()
            )
            .subscribe();
    }

    // 8. Lifecycle
    ngOnInit(): void {
        this.loadData();
    }

    // 9. Public methods
    onToggleDimension(is3D: boolean): void {
        this.is3D.set(is3D);
        const containerRef = this.canvasContainer();
        if (containerRef) {
            this.sceneService.switchDimension(containerRef.nativeElement, is3D);
        }
        void this.startSimulation();
    }

    onMaxEntitiesChange(value: number | null): void {
        if (value === null) return;
        // The backend rejects values below the minimum with 400.
        this.maxEntities.set(Math.max(GRAPH_VISUALIZATION_MIN_ENTITIES, Math.round(value)));
        this.closeDetailPanel();
        this.loadData();
    }

    onSearchTermChange(term: string): void {
        this.searchTerm.set(term);
        this.searchTrigger$.next(term);
    }

    onToggleLabels(visible: boolean): void {
        this.labelsVisible.set(visible);
        this.sceneService.setLabelsVisible(visible);
        if (visible) {
            this.hoveredNodeTitle.set(null);
        }
    }

    onTypeFilterChange(filterIndex: number, checked: boolean): void {
        this.entityTypeFilters.update((filters) => {
            const updated = [...filters];
            updated[filterIndex] = { ...updated[filterIndex], checked };
            return updated;
        });
        this.applyTypeFilters();
    }

    onCanvasPointerDown(event: PointerEvent): void {
        if (event.button !== 0) return; // Only left button for node interaction
        const containerRef = this.canvasContainer();
        if (!containerRef) return;
        const nodeIndex = this.sceneService.pickNode(event.clientX, event.clientY, containerRef.nativeElement);
        if (nodeIndex >= 0) {
            this.draggedNodeIndex = nodeIndex;
            this.isDragging = false;
            this.clickedEdgeOnDown = -1;
            this.sceneService.setControlsEnabled(false);
            // Fix the node in place during drag
            const simNode = this.simNodes[nodeIndex];
            if (simNode) {
                simNode.fx = simNode.x;
                simNode.fy = simNode.y;
                if (this.is3D()) simNode.fz = simNode.z ?? 0;
            }
            this.simulation?.reheat();
        } else {
            // Track edge for click detection
            this.clickedEdgeOnDown = this.sceneService.pickEdge(
                event.clientX,
                event.clientY,
                containerRef.nativeElement
            );
        }
    }

    onCanvasPointerUp(): void {
        if (this.draggedNodeIndex !== null) {
            if (!this.isDragging) {
                // It was a click, not a drag — select the node
                this.selectedNodeIndex.set(this.draggedNodeIndex);
                this.selectedEdgeIndex.set(null);
            }
            this.releaseDraggedNode();
        } else if (this.clickedEdgeOnDown >= 0) {
            // Edge click
            this.selectedEdgeIndex.set(this.clickedEdgeOnDown);
            this.selectedNodeIndex.set(null);
            this.clickedEdgeOnDown = -1;
        }
    }

    onCanvasPointerLeave(): void {
        if (this.draggedNodeIndex !== null) {
            this.releaseDraggedNode();
        }
        this.clickedEdgeOnDown = -1;
        this.sceneService.setHoveredNode(null);
        this.sceneService.setHoveredEdge(null);
        this.hoveredNodeTitle.set(null);
    }

    onSelectNode(nodeIndex: number): void {
        this.selectedNodeIndex.set(nodeIndex);
        this.selectedEdgeIndex.set(null);
    }

    retryLoad(): void {
        this.loadData();
    }

    closeDetailPanel(): void {
        this.selectedNodeIndex.set(null);
        this.selectedEdgeIndex.set(null);
        this.nodeDescription.set(null);
        this.edgeDescription.set(null);
    }

    // 10. Private methods
    private loadData(): void {
        this.hoveredNodeTitle.set(null);
        this.viewState.set('loading');
        const search = this.searchTerm().trim() || undefined;
        this.loadTrigger$.next({ ragId: this.ragId(), maxEntities: this.maxEntities(), search });
    }

    private handleDataLoaded(data: GraphVisualizationData): void {
        if (data.entities.length === 0) {
            this.closeDetailPanel();
            this.entityTypeFilters.set([]);
            this.errorMessage.set(
                this.searchTerm().trim() ? 'No entities match your search' : 'This graph has no entities to display'
            );
            this.viewState.set('no-matches');
            return;
        }

        if (!this.toolbarVisible()) {
            this.maxEntities.set(data.entities.length);
        }
        this.toolbarVisible.set(true);
        this.entityCount.set(data.entities.length);
        this.totalEntityCount.set(data.total_entities);
        this.relationshipCount.set(data.total_relationships);

        this.sceneService.buildGraph(data.entities, data.relationships);
        if (this.sceneService.isSceneInitialized()) {
            // Keep the renderer and camera; swap the meshes in place and re-run the layout.
            this.sceneService.refreshGraph();
            void this.startSimulation();
        }
        this.applySearchHighlight();
        this.buildEntityTypeFilters(data.entities);
        this.applyTypeFilters();

        this.viewState.set('ready');
    }

    private handleError(error: HttpErrorResponse): void {
        if (isGraphNotIndexedError(error)) {
            this.viewState.set('not-indexed');
            this.errorMessage.set(GRAPH_NOT_INDEXED_MESSAGE);
        } else if (error.status === HttpStatusCode.ServiceUnavailable) {
            this.viewState.set('error');
            this.errorMessage.set('GraphRAG is not available on this server');
        } else {
            this.viewState.set('error');
            this.errorMessage.set(error.error?.message ?? 'Failed to load graph visualization data');
        }
    }

    private async initializeScene(canvas: HTMLCanvasElement, container: HTMLElement): Promise<void> {
        const generation = ++this.sceneGeneration;
        this.sceneCanvas = canvas;

        await this.sceneService.loadDependencies();
        if (this.destroyed || generation !== this.sceneGeneration) return;

        this.sceneService.initScene(canvas, container, this.is3D());
        await this.startSimulation();
    }

    /** Stop the simulation and dispose the scene; any in-flight initialization is abandoned. */
    private teardownScene(): void {
        this.sceneGeneration++;
        this.simulationGeneration++;
        this.stopSimulation();
        this.sceneService.dispose();
        this.sceneCanvas = null;
    }

    private async startSimulation(): Promise<void> {
        const generation = ++this.simulationGeneration;
        // Stop the previous layout right away, so it never runs alongside the one replacing it.
        this.stopSimulation();

        const d3 = await import('d3-force-3d');
        if (this.destroyed || generation !== this.simulationGeneration || !this.sceneService.isSceneInitialized()) {
            return;
        }

        const nodes = this.sceneService.getNodes();
        const edges = this.sceneService.getEdges();
        const is3D = this.is3D();

        const simNodes: SimulationNode[] = nodes.map((node) => ({
            index: node.index,
            x: node.x,
            y: node.y,
            z: is3D ? (Math.random() - 0.5) * INITIAL_LAYOUT_SPREAD : undefined,
        }));
        const simLinks = edges.map((edge) => ({ source: edge.sourceIndex, target: edge.targetIndex }));

        // d3's timer schedules a frame per tick; outside the zone it does not trigger change detection.
        const simulation = this.ngZone.runOutsideAngular(() =>
            d3
                .forceSimulation(simNodes, is3D ? 3 : 2)
                .force('link', d3.forceLink(simLinks).distance(SIMULATION_LINK_DISTANCE))
                .force('charge', d3.forceManyBody().strength(SIMULATION_CHARGE_STRENGTH))
                .force('center', d3.forceCenter(0, 0, is3D ? 0 : undefined))
                .on('tick', () => this.sceneService.updateNodePositions(simNodes))
        );

        this.simNodes = simNodes;
        this.simulation = {
            stop: () => simulation.stop(),
            reheat: () => this.ngZone.runOutsideAngular(() => simulation.alpha(DRAG_REHEAT_ALPHA).restart()),
        };
    }

    private stopSimulation(): void {
        this.simulation?.stop();
        this.simulation = null;
    }

    /** Runs outside the Angular zone — see `pointerMoveEffect`. */
    private handleCanvasPointerMove(event: PointerEvent): void {
        const containerRef = this.canvasContainer();
        if (!containerRef) return;

        if (this.draggedNodeIndex !== null) {
            this.isDragging = true;
            this.setHoverTooltip(null);
            const worldPos = this.sceneService.screenToWorld(event.clientX, event.clientY, containerRef.nativeElement);
            if (!worldPos) return;

            const simNode = this.simNodes[this.draggedNodeIndex];
            if (simNode) {
                simNode.fx = worldPos.x;
                simNode.fy = worldPos.y;
                if (this.is3D() && worldPos.z !== undefined) simNode.fz = worldPos.z;
            }
            return;
        }

        // Hover detection — node first, then edge
        const nodeIndex = this.sceneService.pickNode(event.clientX, event.clientY, containerRef.nativeElement);
        if (nodeIndex >= 0) {
            this.sceneService.setHoveredEdge(null);
            this.sceneService.setHoveredNode(nodeIndex);
            if (!this.labelsVisible()) {
                this.setHoverTooltip(nodeIndex, containerRef.nativeElement);
            }
        } else {
            this.sceneService.setHoveredNode(null);
            this.setHoverTooltip(null);
            const edgeIndex = this.sceneService.pickEdge(event.clientX, event.clientY, containerRef.nativeElement);
            this.sceneService.setHoveredEdge(edgeIndex >= 0 ? edgeIndex : null);
        }
    }

    /** Updates the hover tooltip, re-entering the Angular zone only when its content or position changed. */
    private setHoverTooltip(nodeIndex: number | null, container?: HTMLElement): void {
        const node = nodeIndex === null ? undefined : this.sceneService.getNodes()[nodeIndex];
        const title = node?.title ?? null;
        const position =
            node && container ? this.sceneService.projectToScreen(node.index, container) : this.hoverPosition();
        const current = this.hoverPosition();
        const positionChanged = position !== null && (position.x !== current.x || position.y !== current.y);
        if (title === this.hoveredNodeTitle() && (title === null || !positionChanged)) return;

        this.ngZone.run(() => {
            this.hoveredNodeTitle.set(title);
            if (title !== null && position) {
                this.hoverPosition.set(position);
            }
        });
    }

    private releaseDraggedNode(): void {
        const simNode = this.draggedNodeIndex === null ? undefined : this.simNodes[this.draggedNodeIndex];
        if (simNode) {
            simNode.fx = null;
            simNode.fy = null;
            simNode.fz = null;
        }
        this.draggedNodeIndex = null;
        this.isDragging = false;
        this.sceneService.setControlsEnabled(true);
    }

    private buildEntityTypeFilters(entities: VisualizationEntity[]): void {
        const typeCounts = new Map<string | null, number>();
        for (const entity of entities) {
            const type = entity.type;
            typeCounts.set(type, (typeCounts.get(type) ?? 0) + 1);
        }

        const filters: EntityTypeFilter[] = [];
        for (const [type, count] of typeCounts) {
            filters.push({
                type,
                label: `${type ?? 'Unknown'} (${count})`,
                checked: true,
                color: this.sceneService.getTypeColor(type),
            });
        }
        filters.sort((a, b) => a.label.localeCompare(b.label));
        this.entityTypeFilters.set(filters);
    }

    private applySearchHighlight(): void {
        const term = this.searchTerm().trim();
        if (term) {
            const lower = term.toLowerCase();
            const nodes = this.sceneService.getNodes();
            const matchedIndices = new Set<number>();
            for (const node of nodes) {
                if (node.title.toLowerCase().includes(lower)) {
                    matchedIndices.add(node.index);
                }
            }
            this.sceneService.setSearchHighlight(matchedIndices);
        } else {
            this.sceneService.setSearchHighlight(null);
        }
    }

    private applyTypeFilters(): void {
        const filters = this.entityTypeFilters();
        const allChecked = filters.every((filter) => filter.checked);

        if (allChecked) {
            this.sceneService.setVisibleTypes(null);
        } else {
            const visibleTypes = new Set<string | null>(
                filters.filter((filter) => filter.checked).map((filter) => filter.type)
            );
            this.sceneService.setVisibleTypes(visibleTypes);
        }
    }
}
