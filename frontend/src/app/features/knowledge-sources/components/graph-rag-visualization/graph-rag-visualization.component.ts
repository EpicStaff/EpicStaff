import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
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
import { ButtonComponent, CheckboxComponent, LoadingSpinnerComponent, SearchComponent } from '@shared/components';

import {
    GraphVisualizationData,
    VisualizationCommunity,
    VisualizationEntity,
} from '../../models/graph-visualization.model';
import { GraphRagService } from '../../services/graph-rag.service';
import { GraphEdge, GraphNode, GraphSceneService } from './graph-scene.service';

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
    imports: [ButtonComponent, CheckboxComponent, FormsModule, LoadingSpinnerComponent, SearchComponent],
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
    readonly communitySidebarOpen = signal(true);
    readonly selectedNodeIndex = signal<number | null>(null);
    readonly selectedEdgeIndex = signal<number | null>(null);
    readonly hoveredNodeTitle = signal<string | null>(null);
    readonly hoverPosition = signal<{ x: number; y: number }>({ x: 0, y: 0 });

    readonly entityCount = signal(0);
    readonly totalEntityCount = signal(0);
    readonly relationshipCount = signal(0);
    readonly communityCount = signal(0);

    readonly communities = signal<VisualizationCommunity[]>([]);
    readonly highlightedCommunityId = signal<string | null>(null);

    readonly entityTypeFilters = signal<EntityTypeFilter[]>([]);

    readonly selectedNode = computed<GraphNode | null>(() => {
        const index = this.selectedNodeIndex();
        if (index === null) return null;
        const nodes = this.sceneService.getNodes();
        return nodes[index] ?? null;
    });

    readonly selectedNodeCommunities = computed<string[]>(() => {
        const node = this.selectedNode();
        if (!node) return [];
        const comms = this.communities();
        return node.communityIds
            .map((id) => comms.find((c) => c.id === id)?.title)
            .filter((title): title is string => !!title);
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

    // 4. Effects
    /** When the canvas element becomes available (after viewState switches to 'ready'), init the scene. */
    private readonly canvasEffect = effect(() => {
        const canvasRef = this.graphCanvas();
        const containerRef = this.canvasContainer();
        if (canvasRef && containerRef && this.pendingData) {
            this.initializeScene(canvasRef.nativeElement, containerRef.nativeElement);
        }
    });

    // 6. Private fields
    private readonly graphRagService = inject(GraphRagService);
    private readonly destroyRef = inject(DestroyRef);
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
    private draggedNodeIndex: number | null = null;
    private isDragging = false;
    private clickedEdgeOnDown = -1;

    constructor() {
        // Auto-load when the component is created (it is conditionally rendered via @if).
    }

    ngOnInit() {
        this.loadData();
    }

    // 8. Lifecycle
    ngOnDestroy(): void {
        this.stopSimulation();
        this.sceneService.dispose();
    }

    onToggleDimension(): void {
        const newIs3D = !this.is3D();
        this.is3D.set(newIs3D);
        const containerRef = this.canvasContainer();
        if (containerRef) {
            this.sceneService.switchDimension(containerRef.nativeElement, newIs3D);
        }
        this.restartSimulation();
    }

    onMaxEntitiesSliderChange(event: Event): void {
        const value = (event.target as HTMLInputElement).valueAsNumber;
        this.maxEntities.set(value);
        this.loadData();
    }

    onSearchTermChange(term: string): void {
        this.searchTerm.set(term);
        if (!term.trim()) {
            this.sceneService.setSearchHighlight(null);
            return;
        }
        const lower = term.toLowerCase();
        const nodes = this.sceneService.getNodes();
        const indices = new Set<number>();
        for (const node of nodes) {
            if (node.title.toLowerCase().includes(lower)) {
                indices.add(node.index);
            }
        }
        this.sceneService.setSearchHighlight(indices.size > 0 ? indices : null);
    }

    onToggleLabels(): void {
        const visible = !this.labelsVisible();
        this.labelsVisible.set(visible);
        this.sceneService.setLabelsVisible(visible);
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
        } else {
            // Click on empty space — clear selection
            this.selectedNodeIndex.set(null);
            this.selectedEdgeIndex.set(null);
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

    onCommunityClick(communityId: string): void {
        if (this.highlightedCommunityId() === communityId) {
            this.highlightedCommunityId.set(null);
            this.sceneService.setHighlightedNodes(null);
            return;
        }
        this.highlightedCommunityId.set(communityId);
        const community = this.communities().find((c) => c.id === communityId);
        if (!community) return;

        const memberIds = new Set(community.entity_ids);
        const nodes = this.sceneService.getNodes();
        const indices = new Set<number>();
        for (const node of nodes) {
            if (memberIds.has(node.id) || memberIds.has(node.title)) {
                indices.add(node.index);
            }
        }
        this.sceneService.setHighlightedNodes(indices);
    }

    onToggleCommunitySidebar(): void {
        this.communitySidebarOpen.set(!this.communitySidebarOpen());
    }

    closeDetailPanel(): void {
        this.selectedNodeIndex.set(null);
        this.selectedEdgeIndex.set(null);
    }

    // 10. Private methods
    private loadData(): void {
        this.viewState.set('loading');
        this.graphRagService
            .getVisualizationData(this.ragId(), this.maxEntities())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (data) => this.handleDataLoaded(data),
                error: (error) => this.handleError(error),
            });
    }

    private handleDataLoaded(data: GraphVisualizationData): void {
        if (data.entities.length === 0) {
            this.viewState.set('empty');
            return;
        }

        this.entityCount.set(data.entities.length);
        this.totalEntityCount.set(data.total_entities);
        this.relationshipCount.set(data.relationships.length);
        this.communityCount.set(data.communities.length);
        this.communities.set(data.communities);
        this.buildEntityTypeFilters(data.entities);

        this.sceneService.buildGraph(data.entities, data.relationships);

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
