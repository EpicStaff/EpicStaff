import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    ElementRef,
    inject,
    input,
    OnDestroy,
    OnInit,
    signal,
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

import { GraphVisualizationData, VisualizationEntity } from '../../models/graph-visualization.model';
import { GraphRagService } from '../../services/graph-rag.service';
import { GraphEdge, GraphNode } from './graph-scene.model';
import { GraphSceneService } from './graph-scene.service';

type ViewState = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

interface EntityTypeFilter {
    type: string | null;
    label: string;
    checked: boolean;
    color: string;
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
export class GraphRagVisualizationComponent implements OnInit, OnDestroy {
    // 1. Inputs
    readonly ragId = input.required<number>();

    // 2. ViewChild
    private readonly graphCanvas = viewChild<ElementRef<HTMLCanvasElement>>('graphCanvas');
    private readonly canvasContainer = viewChild<ElementRef<HTMLElement>>('canvasContainer');

    // 3. Signals & Computed
    readonly viewState = signal<ViewState>('idle');
    readonly errorMessage = signal('');
    readonly is3D = signal(false);
    readonly maxEntities = signal(200);
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

    // 4. Effects
    /** When the canvas element becomes available (after viewState switches to 'ready'), init the scene. */
    private readonly canvasEffect = effect(() => {
        const canvasRef = this.graphCanvas();
        const containerRef = this.canvasContainer();
        if (canvasRef && containerRef && this.pendingData) {
            this.initializeScene(canvasRef.nativeElement, containerRef.nativeElement);
        }
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

    readonly detailPanelOpen = computed(() => this.selectedNode() !== null || this.selectedEdge() !== null);

    // 5. Sidebar
    private static readonly SIDEBAR_STORAGE_KEY = 'graph-viz-sidebar';
    private static readonly DETAIL_PANEL_STORAGE_KEY = 'graph-viz-detail';
    private readonly sidebarWidthService = inject(SidebarWidthService);
    readonly sidebarWidth = this.sidebarWidthService.getWidth(GraphRagVisualizationComponent.SIDEBAR_STORAGE_KEY, {
        defaultWidth: 220,
        minWidth: 160,
        maxWidth: 400,
    });
    readonly detailPanelWidth = this.sidebarWidthService.getWidth(
        GraphRagVisualizationComponent.DETAIL_PANEL_STORAGE_KEY,
        {
            defaultWidth: 320,
            minWidth: 240,
            maxWidth: 600,
        }
    );

    // 6. Private fields
    private readonly graphRagService = inject(GraphRagService);
    private readonly sceneService = inject(GraphSceneService);

    private simulation: { stop: () => void; reheat: () => void } | null = null;
    private pendingData: GraphVisualizationData | null = null;
    private initialized = false;
    private simNodes: Array<{
        index: number;
        x: number;
        y: number;
        z?: number;
        fx?: number | null;
        fy?: number | null;
        fz?: number | null;
    }> = [];
    private readonly loadTrigger$ = new Subject<{ ragId: number; maxEntities: number; search?: string }>();
    private readonly searchTrigger$ = new Subject<string>();
    private draggedNodeIndex: number | null = null;
    private isDragging = false;
    private clickedEdgeOnDown = -1;

    constructor() {
        this.loadTrigger$
            .pipe(
                switchMap(({ ragId, maxEntities, search }) =>
                    this.graphRagService.getVisualizationData(ragId, maxEntities, search).pipe(
                        tap((data) => this.handleDataLoaded(data)),
                        catchError((error) => {
                            this.handleError(error);
                            return EMPTY;
                        })
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe();

        this.searchTrigger$.pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed()).subscribe(() => {
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

    ngOnInit() {
        this.loadData();
    }

    // 8. Lifecycle
    ngOnDestroy(): void {
        this.stopSimulation();
        this.sceneService.dispose();
    }

    onToggleDimension(is3D: boolean): void {
        this.is3D.set(is3D);
        const containerRef = this.canvasContainer();
        if (containerRef) {
            this.sceneService.switchDimension(containerRef.nativeElement, is3D);
        }
        this.restartSimulation();
    }

    onMaxEntitiesChange(value: number | null): void {
        if (value === null) return;
        this.maxEntities.set(value);
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

    onCanvasPointerMove(event: PointerEvent): void {
        const containerRef = this.canvasContainer();
        if (!containerRef) return;

        if (this.draggedNodeIndex !== null) {
            this.isDragging = true;
            this.hoveredNodeTitle.set(null);
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
                this.updateHoverTooltip(nodeIndex, containerRef.nativeElement);
            }
        } else {
            this.sceneService.setHoveredNode(null);
            this.hoveredNodeTitle.set(null);
            const edgeIndex = this.sceneService.pickEdge(event.clientX, event.clientY, containerRef.nativeElement);
            this.sceneService.setHoveredEdge(edgeIndex >= 0 ? edgeIndex : null);
        }
    }

    onCanvasPointerUp(): void {
        if (this.draggedNodeIndex !== null) {
            if (!this.isDragging) {
                // It was a click, not a drag — select the node
                this.selectedNodeIndex.set(this.draggedNodeIndex);
                this.selectedEdgeIndex.set(null);
            }
            // Release the fixed position
            const simNode = this.simNodes[this.draggedNodeIndex];
            if (simNode) {
                simNode.fx = null;
                simNode.fy = null;
                simNode.fz = null;
            }
            this.draggedNodeIndex = null;
            this.isDragging = false;
            this.sceneService.setControlsEnabled(true);
        } else if (this.clickedEdgeOnDown >= 0) {
            // Edge click
            this.selectedEdgeIndex.set(this.clickedEdgeOnDown);
            this.selectedNodeIndex.set(null);
            this.clickedEdgeOnDown = -1;
        }
    }

    onCanvasPointerLeave(): void {
        if (this.draggedNodeIndex !== null) {
            const simNode = this.simNodes[this.draggedNodeIndex];
            if (simNode) {
                simNode.fx = null;
                simNode.fy = null;
                simNode.fz = null;
            }
            this.draggedNodeIndex = null;
            this.isDragging = false;
            this.sceneService.setControlsEnabled(true);
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
        this.viewState.set('loading');
        const search = this.searchTerm().trim() || undefined;
        this.loadTrigger$.next({ ragId: this.ragId(), maxEntities: this.maxEntities(), search });
    }

    private handleDataLoaded(data: GraphVisualizationData): void {
        if (data.entities.length === 0) {
            this.viewState.set('empty');
            return;
        }

        if (!this.toolbarVisible()) {
            this.maxEntities.set(data.entities.length);
        }
        this.toolbarVisible.set(true);
        this.entityCount.set(data.entities.length);
        this.totalEntityCount.set(data.total_entities);
        this.relationshipCount.set(data.total_relationships);
        this.buildEntityTypeFilters(data.entities);

        this.sceneService.buildGraph(data.entities, data.relationships);
        this.applySearchHighlight();

        if (this.initialized) {
            // Scene already exists — reinitialize with new data directly
            const canvasRef = this.graphCanvas();
            const containerRef = this.canvasContainer();
            if (canvasRef && containerRef) {
                this.initializeScene(canvasRef.nativeElement, containerRef.nativeElement);
                return;
            }
        }

        // Store pending data so the effect can pick it up when the canvas appears.
        this.pendingData = data;
        this.viewState.set('ready');
    }

    private handleError(error: { status?: number; error?: { message?: string } }): void {
        if (error.status === 404) {
            this.viewState.set('empty');
            this.errorMessage.set('No index data -- run indexing first');
        } else if (error.status === 503) {
            this.viewState.set('error');
            this.errorMessage.set('GraphRAG is not available on this server');
        } else {
            this.viewState.set('error');
            this.errorMessage.set(error.error?.message ?? 'Failed to load graph visualization data');
        }
    }

    private async initializeScene(canvas: HTMLCanvasElement, container: HTMLElement): Promise<void> {
        await this.sceneService.loadDependencies();

        if (this.initialized) {
            this.stopSimulation();
            this.sceneService.dispose();
        }

        this.sceneService.initScene(canvas, container, this.is3D());
        this.initialized = true;
        this.pendingData = null;

        this.startSimulation();
    }

    private async startSimulation(): Promise<void> {
        this.stopSimulation();

        const nodes = this.sceneService.getNodes();
        const edges = this.sceneService.getEdges();

        const is3D = this.is3D();
        const numDimensions = is3D ? 3 : 2;
        const d3 = await import('d3-force-3d');

        const simNodes = nodes.map((n) => ({
            index: n.index,
            x: n.x,
            y: n.y,
            z: is3D ? (Math.random() - 0.5) * 200 : undefined,
        }));

        const simLinks = edges.map((e) => ({
            source: e.sourceIndex,
            target: e.targetIndex,
        }));

        const simulation = d3
            .forceSimulation(simNodes, numDimensions)
            .force('link', d3.forceLink(simLinks).distance(40))
            .force('charge', d3.forceManyBody().strength(-50))
            .force('center', d3.forceCenter(0, 0, is3D ? 0 : undefined));

        simulation.on('tick', () => {
            this.sceneService.updateNodePositions(simNodes as Array<{ x: number; y: number; z?: number }>);
        });

        this.simNodes = simNodes;
        this.simulation = {
            stop: () => simulation.stop(),
            reheat: () => simulation.alpha(0.3).restart(),
        };
    }

    private stopSimulation(): void {
        this.simulation?.stop();
        this.simulation = null;
    }

    private restartSimulation(): void {
        this.startSimulation();
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

    private updateHoverTooltip(nodeIndex: number | null, container: HTMLElement): void {
        if (nodeIndex === null) {
            this.hoveredNodeTitle.set(null);
            return;
        }
        const nodes = this.sceneService.getNodes();
        const node = nodes[nodeIndex];
        if (!node) {
            this.hoveredNodeTitle.set(null);
            return;
        }
        this.hoveredNodeTitle.set(node.title);
        const screenPos = this.sceneService.projectToScreen(nodeIndex, container);
        if (screenPos) {
            this.hoverPosition.set(screenPos);
        }
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
        const allChecked = filters.every((f) => f.checked);

        if (allChecked) {
            this.sceneService.setVisibleTypes(null);
        } else {
            const visibleTypes = new Set<string | null>(filters.filter((f) => f.checked).map((f) => f.type));
            this.sceneService.setVisibleTypes(visibleTypes);
        }
    }
}
