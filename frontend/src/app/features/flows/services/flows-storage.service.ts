import { Injectable, signal, computed, inject } from '@angular/core';
import { Observable, of } from 'rxjs';
import {
    tap,
    map,
    delay,
    shareReplay,
    catchError,
    switchMap,
} from 'rxjs/operators';

import {
    GraphDto,
    CreateGraphDtoRequest,
    UpdateGraphDtoRequest,
} from '../models/graph.model';
import { FlowsApiService } from './flows-api.service';
import { SearchFilterChange } from '../../../shared/components/filters-list/filters-list.component';

const TEMPLATE_FLOWS: GraphDto[] = [];

@Injectable({
    providedIn: 'root',
})
export class FlowsStorageService {
    private readonly flowsApiService = inject(FlowsApiService);

    // --- State Signals ---
    private flowsSignal = signal<GraphDto[]>([]);
    private flowsLoaded = signal<boolean>(false);
    private templatesSignal = signal<GraphDto[]>([]);
    private templatesLoaded = signal<boolean>(false);
    private filterSignal = signal<SearchFilterChange | null>(null);

    // --- Public State Accessors ---
    public readonly isFlowsLoaded = this.flowsLoaded.asReadonly();
    public readonly isTemplatesLoaded = this.templatesLoaded.asReadonly();

    public readonly filteredFlows = computed(() => {
        const flows = this.flowsSignal();
        const filter = this.filterSignal();
        let filtered = flows;
        if (filter) {
            if (filter.searchTerm) {
                filtered = filtered.filter((f) =>
                    f.name
                        .toLowerCase()
                        .includes(filter.searchTerm.toLowerCase())
                );
            }
        }
        // Always sort by id descending
        return filtered.slice().sort((a, b) => b.id - a.id);
    });

    public readonly filteredTemplates = computed(() => {
        const templates = this.templatesSignal();
        const filter = this.filterSignal();
        if (!filter) return templates;
        let filtered = templates;
        if (filter.searchTerm) {
            filtered = filtered.filter((t) =>
                t.name.toLowerCase().includes(filter.searchTerm.toLowerCase())
            );
        }
        return filtered;
    });

    // --- State Mutators ---
    public setFlows(flows: GraphDto[]) {
        this.flowsSignal.set(flows);
        this.flowsLoaded.set(true);
    }

    public setTemplates(templates: GraphDto[]) {
        this.templatesSignal.set(templates);
        this.templatesLoaded.set(true);
    }

    public setFilter(filter: SearchFilterChange | null) {
        // Only update filter if it's different from current filter
        const currentFilter = this.filterSignal();

        // Check if filter is the same as current filter
        if (currentFilter === null && filter === null) {
            return;
        }

        // If either is null but not both, they're different
        if (currentFilter === null || filter === null) {
            this.filterSignal.set(filter);
            return;
        }

        // Compare searchTerm
        const searchTermChanged =
            currentFilter.searchTerm !== filter.searchTerm;

        // Only update if there's a change
        if (searchTermChanged) {
            this.filterSignal.set(filter);
        }
    }

    // Get the current filter value
    public getCurrentFilter(): SearchFilterChange | null {
        return this.filterSignal();
    }

    // --- Data Fetching Methods ---
    public getFlows(forceRefresh = false): Observable<GraphDto[]> {
        if (this.flowsLoaded() && !forceRefresh) {
            return of(this.flowsSignal());
        }
        return this.flowsApiService.getGraphsLight().pipe(
            tap((flows) => {
                this.setFlows(flows);
            }),
        
            shareReplay(1),
            catchError(() => {
                this.flowsLoaded.set(false);
                return of([]);
            })
        );
    }

    public getFlowTemplates(forceRefresh = false): Observable<GraphDto[]> {
        if (this.templatesLoaded() && !forceRefresh) {
            return of(this.templatesSignal());
        }
        return of(TEMPLATE_FLOWS).pipe(
            delay(500),
            tap((templates) => {
                this.setTemplates(templates);
            }),
            shareReplay(1)
        );
    }

    public getFlowById(id: number): Observable<GraphDto | undefined> {
        const cachedFlow: GraphDto | undefined = this.flowsSignal().find(
            (flow) => flow.id === id
        );
        if (cachedFlow) {
            return of(cachedFlow);
        }
        return this.flowsApiService
            .getGraphById(id)
            .pipe(catchError(() => of(undefined)));
    }

    // --- CRUD Methods ---
    public createFlow(flowData: CreateGraphDtoRequest): Observable<GraphDto> {
        return this.flowsApiService.createGraph(flowData).pipe(
            tap((newFlow) => {
                this.addFlowToCache(newFlow);
            })
        );
    }

    public updateFlow(flowData: UpdateGraphDtoRequest): Observable<GraphDto> {
        return this.flowsApiService.updateGraph(flowData.id, flowData).pipe(
            tap((updatedFlow) => {
                const currentFlows = this.flowsSignal();
                const index = currentFlows.findIndex(
                    (f) => f.id === updatedFlow.id
                );
                if (index !== -1) {
                    const updatedFlowsList = [...currentFlows];
                    updatedFlowsList[index] = updatedFlow;
                    this.flowsSignal.set(updatedFlowsList);
                }
            })
        );
    }

    public patchUpdateFlow(
        id: number,
        updateData: Partial<GraphDto>
    ): Observable<GraphDto> {
        return this.getFlowById(id).pipe(
            switchMap((currentFlow: GraphDto | undefined) => {
                if (!currentFlow)
                    throw new Error('Flow not found for patching');
                const updatedPayload: UpdateGraphDtoRequest = {
                    id: currentFlow.id,
                    name: updateData.name || currentFlow.name,
                    description:
                        updateData.description || currentFlow.description,
                    metadata: updateData.metadata || currentFlow.metadata,
                    tags: updateData.tags || currentFlow.tags || [],
                };
                return this.updateFlow(updatedPayload);
            })
        );
    }

    public deleteFlow(id: number): Observable<void> {
        return this.flowsApiService.deleteGraph(id).pipe(
            tap(() => {
                const currentFlows = this.flowsSignal();
                this.flowsSignal.set(currentFlows.filter((f) => f.id !== id));
            })
        );
    }

    public copyFlow(sourceId: number, newName: string): Observable<GraphDto> {
        return this.flowsApiService.getGraphById(sourceId).pipe(
            switchMap((sourceFlow: GraphDto) => {
                const payload: GraphDto = {
                    id: sourceFlow.id,
                    name: newName,
                    description: sourceFlow.description,
                    metadata: sourceFlow.metadata,
                    tags: sourceFlow.tags || [],
                    start_node_list: sourceFlow.start_node_list,
                    crew_node_list: sourceFlow.crew_node_list,
                    python_node_list: sourceFlow.python_node_list,
                    edge_list: sourceFlow.edge_list,
                    conditional_edge_list: sourceFlow.conditional_edge_list,
                    llm_node_list: sourceFlow.llm_node_list,
                    file_extractor_node_list:
                        sourceFlow.file_extractor_node_list,
                    webhook_trigger_node_list: sourceFlow.webhook_trigger_node_list,
                    telegram_trigger_node_list: sourceFlow.telegram_trigger_node_list,
                    end_node_list: sourceFlow.end_node_list,
                    subgraph_node_list: sourceFlow.subgraph_node_list,
                    audio_transcription_node_list: sourceFlow.audio_transcription_node_list,
                    decision_table_node_list: sourceFlow.decision_table_node_list,
                };
                return this.flowsApiService.copyGraph(payload).pipe(
                    tap((created) => this.addFlowToCache(created))
                );
            })
        );
    }

    // --- Cache Management ---
    public addFlowToCache(newFlow: GraphDto) {
        const currentFlows = this.flowsSignal();
        if (!currentFlows.some((f) => f.id === newFlow.id)) {
            this.flowsSignal.set([newFlow, ...currentFlows]);
        }
    }
}
