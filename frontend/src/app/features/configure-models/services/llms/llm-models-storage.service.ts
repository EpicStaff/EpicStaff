import { computed, inject, Injectable, signal } from '@angular/core';
import { CreateLlmModelRequest, LLMModel } from '@shared/models';
import { LLMModelsService } from '@shared/services';
import { catchError, Observable, of, tap, throwError } from 'rxjs';

@Injectable({
    providedIn: 'root',
})
export class LlmModelsStorageService {
    private readonly llmModelsService = inject(LLMModelsService);

    private modelsSignal = signal<LLMModel[]>([]);
    private loadedProviderIds = signal<Set<number>>(new Set());
    private allModelsLoadedSignal = signal<boolean>(false);

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
        if (!forceRefresh) {
            if (providerId !== undefined && this.loadedProviderIds().has(providerId)) {
                let cached = this.modelsSignal().filter((m) => m.llm_provider === providerId);
                if (isVisible !== undefined) {
                    cached = cached.filter((m) => m.is_visible === isVisible);
                }
                return of(cached);
            }
            if (this.allModelsLoadedSignal()) {
                let cached = this.modelsSignal();
                if (isVisible !== undefined) {
                    cached = cached.filter((m) => m.is_visible === isVisible);
                }
                return of(cached);
            }
        }

        return this.llmModelsService.getLLMModels(providerId, isVisible).pipe(
            tap((models) => {
                if (providerId !== undefined) {
                    this.setModelsForProvider(providerId, models);
                } else {
                    this.setAllModels(models);
                }
            }),
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

    private removeModelFromCache(id: number): void {
        this.modelsSignal.update((current) => current.filter((m) => m.id !== id));
    }
}
