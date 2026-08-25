import { computed, inject, Injectable, signal } from '@angular/core';
import { CreateLlmModelRequest, LLMModel } from '@shared/models';
import { catchError, finalize, map, Observable, of, shareReplay, tap, throwError } from 'rxjs';

import { StorageService } from '../app-storage.service';
import { LLMModelsService } from './llm-models.service';

@Injectable({
    providedIn: 'root',
})
export class LlmModelsStorageService implements StorageService {
    private readonly llmModelsService = inject(LLMModelsService);

    private modelsSignal = signal<LLMModel[]>([]);
    private loadedProviderIds = signal<Set<number>>(new Set());
    private allModelsLoadedSignal = signal<boolean>(false);
    // Shared in-flight "all models" request so concurrent callers (e.g. agent-detail +
    // its embedded llm-model-selector) reuse one HTTP instead of each firing their own.
    private allModelsRequest$?: Observable<LLMModel[]>;

    public readonly models = this.modelsSignal.asReadonly();
    public readonly isAllModelsLoaded = this.allModelsLoadedSignal.asReadonly();

    // Models grouped by provider id, derived from the flat list
    public readonly modelsByProvider = computed(() => {
        const map = new Map<number, LLMModel[]>();
        for (const model of this.modelsSignal()) {
            const group = map.get(model.llm_provider) ?? [];
            group.push(model);
            map.set(model.llm_provider, group);
        }
        return map;
    });

    getModels(providerId?: number, isVisible?: boolean, forceRefresh = false): Observable<LLMModel[]> {
        const applyVisible = (models: LLMModel[]) =>
            isVisible === undefined ? models : models.filter((m) => m.is_visible === isVisible);

        if (!forceRefresh) {
            if (providerId !== undefined && this.loadedProviderIds().has(providerId)) {
                return of(applyVisible(this.modelsSignal().filter((m) => m.llm_provider === providerId)));
            }
            if (this.allModelsLoadedSignal()) {
                return of(applyVisible(this.modelsSignal()));
            }
        }

        // All-models path: share one in-flight request across concurrent callers, then
        // filter per caller. Provider-scoped requests keep their existing per-call behaviour.
        if (providerId === undefined) {
            if (forceRefresh || !this.allModelsRequest$) {
                this.allModelsRequest$ = this.llmModelsService.getLLMModels(undefined, undefined).pipe(
                    tap((models) => this.setAllModels(models)),
                    finalize(() => (this.allModelsRequest$ = undefined)),
                    shareReplay(1)
                );
            }
            return this.allModelsRequest$.pipe(map(applyVisible));
        }

        return this.llmModelsService.getLLMModels(providerId, isVisible).pipe(
            tap((models) => this.setModelsForProvider(providerId, models)),
            catchError((err) => throwError(() => err))
        );
    }

    getModelById(id: number): Observable<LLMModel> {
        const cached = this.models().find((m) => m.id === id);
        if (cached) {
            return of(cached);
        }
        return this.llmModelsService.getLLMModelById(id).pipe(
            tap((model) => this.upsertModelInCache(model)),
            catchError((err) => throwError(() => err))
        );
    }

    createModel(data: CreateLlmModelRequest): Observable<LLMModel> {
        return this.llmModelsService.createModel(data).pipe(
            tap((model) => this.upsertModelInCache(model)),
            catchError((err) => throwError(() => err))
        );
    }

    updateModel(id: number, data: Partial<LLMModel>): Observable<LLMModel> {
        return this.llmModelsService.updateModel(id, data).pipe(
            tap((updated) => this.upsertModelInCache(updated)),
            catchError((err) => throwError(() => err))
        );
    }

    patchModel(id: number, data: Partial<LLMModel>): Observable<LLMModel> {
        return this.llmModelsService.patchModel(id, data).pipe(
            tap((updated) => this.upsertModelInCache(updated)),
            catchError((err) => throwError(() => err))
        );
    }

    deleteModel(id: number): Observable<void> {
        return this.llmModelsService.deleteModel(id).pipe(
            tap(() => this.removeModelFromCache(id)),
            catchError((err) => throwError(() => err))
        );
    }

    private setAllModels(models: LLMModel[]): void {
        this.modelsSignal.set(models);
        this.loadedProviderIds.set(new Set(models.map((m) => m.llm_provider)));
        this.allModelsLoadedSignal.set(true);
    }

    // Replaces models for a single provider without touching others
    private setModelsForProvider(providerId: number, models: LLMModel[]): void {
        this.modelsSignal.update((current) => [...current.filter((m) => m.llm_provider !== providerId), ...models]);
        this.loadedProviderIds.update((set) => {
            const updated = new Set(set);
            updated.add(providerId);
            return updated;
        });
    }

    private upsertModelInCache(model: LLMModel): void {
        this.modelsSignal.update((current) => {
            const index = current.findIndex((m) => m.id === model.id);
            if (index >= 0) {
                const copy = [...current];
                copy[index] = model;
                return copy;
            }
            return [model, ...current];
        });
    }

    clear(): void {
        this.modelsSignal.set([]);
        this.loadedProviderIds.set(new Set());
        this.allModelsLoadedSignal.set(false);
    }

    private removeModelFromCache(id: number): void {
        this.modelsSignal.update((current) => current.filter((m) => m.id !== id));
    }
}
