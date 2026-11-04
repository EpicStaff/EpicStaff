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
import { GraphNode, GraphSceneService } from './graph-scene.service';

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

    readonly entityCount = signal(0);
    readonly relationshipCount = signal(0);
    readonly communityCount = signal(0);

    readonly communities = signal<VisualizationCommunity[]>([]);
    readonly expandedCommunityId = signal<string | null>(null);
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

    private simulation: { stop: () => void } | null = null;
    private pendingData: GraphVisualizationData | null = null;
    private initialized = false;

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

    onCanvasClick(event: MouseEvent): void {
        const containerRef = this.canvasContainer();
        if (!containerRef) return;
        const nodeIndex = this.sceneService.pickNode(event.clientX, event.clientY, containerRef.nativeElement);
        this.selectedNodeIndex.set(nodeIndex >= 0 ? nodeIndex : null);
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

        const entityIds = new Set(community.entity_ids);
        const nodes = this.sceneService.getNodes();
        const indices = new Set<number>();
        for (const node of nodes) {
            if (node.communityIds.some((id) => entityIds.has(id)) || entityIds.has(node.title)) {
                indices.add(node.index);
            }
        }
        this.sceneService.setHighlightedNodes(indices);
    }

    onToggleCommunityExpand(communityId: string): void {
        this.expandedCommunityId.set(this.expandedCommunityId() === communityId ? null : communityId);
    }

    onToggleCommunitySidebar(): void {
        this.communitySidebarOpen.set(!this.communitySidebarOpen());
    }

    closeDetailPanel(): void {
        this.selectedNodeIndex.set(null);
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
        this.relationshipCount.set(data.relationships.length);
        this.communityCount.set(data.communities.length);
        this.communities.set(data.communities);
        this.buildEntityTypeFilters(data.entities);

        this.sceneService.buildGraph(data.entities, data.relationships);

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

        if (this.is3D()) {
            const d3 = await import('d3-force-3d');
            const simNodes = nodes.map((n) => ({
                index: n.index,
                x: n.x,
                y: n.y,
                z: n.z,
            }));

            const simLinks = edges.map((e) => ({
                source: e.sourceIndex,
                target: e.targetIndex,
            }));

            const simulation = d3
                .forceSimulation(simNodes)
                .force('link', d3.forceLink(simLinks).distance(40))
                .force('charge', d3.forceManyBody().strength(-50))
                .force('center', d3.forceCenter(0, 0, 0));

            simulation.on('tick', () => {
                this.sceneService.updateNodePositions(simNodes as Array<{ x: number; y: number; z?: number }>);
            });

            this.simulation = { stop: () => simulation.stop() };
        } else {
            const d3 = await import('d3-force');
            const simNodes = nodes.map((n) => ({
                index: n.index,
                x: n.x,
                y: n.y,
            }));

            const simLinks = edges.map((e) => ({
                source: e.sourceIndex,
                target: e.targetIndex,
            }));

            const simulation = d3
                .forceSimulation(simNodes)
                .force('link', d3.forceLink(simLinks).distance(40))
                .force('charge', d3.forceManyBody().strength(-50))
                .force('center', d3.forceCenter(0, 0));

            simulation.on('tick', () => {
                this.sceneService.updateNodePositions(simNodes as Array<{ x: number; y: number }>);
            });

            this.simulation = { stop: () => simulation.stop() };
        }
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
