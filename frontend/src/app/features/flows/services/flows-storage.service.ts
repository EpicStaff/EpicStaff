import { computed, inject, Injectable, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, delay, shareReplay, switchMap, tap } from 'rxjs/operators';

import { SearchFilterChange } from '../../../shared/components/filters-list/filters-list.component';
import { CreateGraphDtoRequest, GetGraphLightRequest, GraphDto, UpdateGraphDtoRequest } from '../models/graph.model';
import { FlowsApiService } from './flows-api.service';
import { LabelsStorageService } from './labels-storage.service';

const TEMPLATE_FLOWS: GraphDto[] = [];

@Injectable({
    providedIn: 'root',
})
export class FlowsStorageService {
    private readonly flowsApiService = inject(FlowsApiService);
    private readonly labelsStorage = inject(LabelsStorageService);

    // --- State Signals ---
    private flowsSignal = signal<GetGraphLightRequest[]>([]);
    private flowsLoaded = signal<boolean>(false);
    private templatesSignal = signal<GraphDto[]>([]);
    private templatesLoaded = signal<boolean>(false);
    private filterSignal = signal<SearchFilterChange | null>(null);

    // --- Public State Accessors ---
    public readonly isFlowsLoaded = this.flowsLoaded.asReadonly();
    public readonly isTemplatesLoaded = this.templatesLoaded.asReadonly();
    public readonly flows = this.flowsSignal.asReadonly();

    public selectMode = signal<boolean>(false);
    public selectedFlowIds = signal<number[]>([]);

    public readonly filteredFlows = computed(() => {
        const flows = this.flowsSignal();
        const filter = this.filterSignal();
        let filtered = flows;
        if (filter?.searchTerm) {
            const term = filter.searchTerm.toLowerCase();
            const labels = this.labelsStorage.labels();
            filtered = filtered.filter((f) => {
                if (f.name.toLowerCase().includes(term)) return true;
                return (f.label_ids || []).some((id) => {
                    const label = labels.find((l) => l.id === id);
                    return (
                        label &&
                        (label.name.toLowerCase().includes(term) || label.full_path.toLowerCase().includes(term))
                    );
                });
            });
        }
        return filtered.slice().sort((a, b) => b.id - a.id);
    });

    public readonly filteredTemplates = computed(() => {
        const templates = this.templatesSignal();
        const filter = this.filterSignal();
        if (!filter) return templates;
        let filtered = templates;
        if (filter.searchTerm) {
            filtered = filtered.filter((t) => t.name.toLowerCase().includes(filter.searchTerm.toLowerCase()));
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
        const searchTermChanged = currentFilter.searchTerm !== filter.searchTerm;

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
    public getFlows(
        forceRefresh = false,
        labelFilter?: 'all' | 'unlabeled' | number
    ): Observable<GetGraphLightRequest[]> {
        const isFiltered = labelFilter !== undefined && labelFilter !== 'all';
        const params = this.buildLabelParams(labelFilter);

        // Only use cache for unfiltered "all" requests
        if (this.flowsLoaded() && !forceRefresh && !isFiltered) {
            return of(this.flowsSignal());
        }

        return this.flowsApiService.getGraphsLight(params).pipe(
            tap((flows) => {
                this.flowsSignal.set(flows);
                if (!isFiltered) {
                    this.flowsLoaded.set(true);
                }
            }),
            shareReplay(1),
            catchError(() => {
                if (!isFiltered) this.flowsLoaded.set(false);
                return of([]);
            })
        );
    }

    private buildLabelParams(
        filter?: 'all' | 'unlabeled' | number
    ): { label_id?: number; no_label?: boolean } | undefined {
        if (!filter || filter === 'all') return undefined;
        if (filter === 'unlabeled') return { no_label: true };
        return { label_id: filter as number };
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
        const cachedFlow = this.flowsSignal().find((flow) => flow.id === id) as GraphDto | undefined;
        if (cachedFlow) {
            return of(cachedFlow);
        }
        return this.flowsApiService.getGraphById(id).pipe(catchError(() => of(undefined)));
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
                const index = currentFlows.findIndex((f) => f.id === updatedFlow.id);
                if (index !== -1) {
                    const updatedFlowsList = [...currentFlows];
                    const cleanUpdate = Object.fromEntries(
                        Object.entries(updatedFlow).filter(([, v]) => v !== undefined)
                    ) as GraphDto;
                    updatedFlowsList[index] = { ...currentFlows[index], ...cleanUpdate };
                    this.flowsSignal.set(updatedFlowsList);
                }
            })
        );
    }

    public patchUpdateFlow(id: number, updateData: Partial<GraphDto>): Observable<GraphDto> {
        return this.getFlowById(id).pipe(
            switchMap((currentFlow: GraphDto | undefined) => {
                if (!currentFlow) throw new Error('Flow not found for patching');
                const updatedPayload: UpdateGraphDtoRequest = {
                    id: currentFlow.id,
                    name: updateData.name || currentFlow.name,
                    description: updateData.description || currentFlow.description,
                    metadata: updateData.metadata || currentFlow.metadata,
                    tags: updateData.tags || currentFlow.tags || [],
                };
                return this.updateFlow(updatedPayload);
            })
        );
    }

    public updateFlowLabels(id: number, labelIds: number[]): Observable<GraphDto> {
        return this.flowsApiService.patchGraph(id, { label_ids: labelIds }).pipe(
            tap((updatedFlow) => {
                const currentFlows = this.flowsSignal();
                const index = currentFlows.findIndex((f) => f.id === updatedFlow.id);
                if (index !== -1) {
                    const updatedFlowsList = [...currentFlows];
                    const cleanUpdate = Object.fromEntries(
                        Object.entries(updatedFlow).filter(([, v]) => v !== undefined)
                    ) as GraphDto;
                    updatedFlowsList[index] = { ...currentFlows[index], ...cleanUpdate };
                    this.flowsSignal.set(updatedFlowsList);
                }
            })
        );
    }

    public deleteFlow(id: number): Observable<void> {
        return this.flowsApiService.deleteGraph(id).pipe(
            tap(() => {
                const currentFlows = this.flowsSignal();
                this.flowsSignal.set(
                    currentFlows
                        .filter((f) => f.id !== id)
                        .map((f) => {
                            if (!f.subflows?.length) return f;
                            const updatedSubflows = f.subflows.filter((s) => s.id !== id);
                            if (updatedSubflows.length === f.subflows.length) return f;
                            return { ...f, subflows: updatedSubflows };
                        })
                );
                // Remove deleted flow from export selection
                const currentSelected = this.selectedFlowIds();
                if (currentSelected.includes(id)) {
                    this.selectedFlowIds.set(currentSelected.filter((selectedId) => selectedId !== id));
                }
            })
        );
    }

    public copyFlow(sourceId: number, newName: string): Observable<GraphDto> {
        return this.flowsApiService.copyGraph(sourceId, newName).pipe(tap((created) => this.addFlowToCache(created)));
    }

    // --- Cache Management ---
    public addFlowToCache(newFlow: GraphDto) {
        const currentFlows = this.flowsSignal();
        if (!currentFlows.some((f) => f.id === newFlow.id)) {
            this.flowsSignal.set([newFlow, ...currentFlows]);
        }
    }

    public setSelectMode(mode: boolean): void {
        this.selectMode.set(mode);
        if (!mode) {
            this.selectedFlowIds.set([]);
        }
    }

    public toggleFlowSelection(id: number): void {
        const current = this.selectedFlowIds();
        if (current.includes(id)) {
            this.selectedFlowIds.set(current.filter((item) => item !== id));
        } else {
            this.selectedFlowIds.set([...current, id]);
        }
    }

    public clearSelection(): void {
        this.selectedFlowIds.set([]);
    }

    public selectAllFlows(): void {
        const allFlowIds = this.filteredFlows().map((flow) => flow.id);
        this.selectedFlowIds.set(allFlowIds);
    }

    public deselectAllFlows(): void {
        this.selectedFlowIds.set([]);
    }

    public isAllFlowsSelected(): boolean {
        const allFlowIds = this.filteredFlows().map((flow) => flow.id);
        const selectedIds = this.selectedFlowIds();
        return allFlowIds.length > 0 && allFlowIds.every((id) => selectedIds.includes(id));
    }

    public toggleSelectAllFlows(): void {
        if (this.isAllFlowsSelected()) {
            this.deselectAllFlows();
        } else {
            this.selectAllFlows();
        }
    }
}
