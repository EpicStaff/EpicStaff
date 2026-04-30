import { inject, Injectable, signal } from '@angular/core';
import { CreateEmbeddingModelRequest, EmbeddingModel } from '@shared/models';
import { catchError, Observable, of, tap, throwError } from 'rxjs';

import { EmbeddingModelsService } from './embeddings.service';

@Injectable({
    providedIn: 'root',
})
export class EmbeddingModelsStorageService {
    private readonly embeddingModelsService = inject(EmbeddingModelsService);

    private modelsSignal = signal<EmbeddingModel[]>([]);
    private allModelsLoadedSignal = signal<boolean>(false);

    public readonly models = this.modelsSignal.asReadonly();

    getModels(forceRefresh = false): Observable<EmbeddingModel[]> {
        if (!forceRefresh && this.allModelsLoadedSignal()) {
            return of(this.modelsSignal());
        }

        return this.embeddingModelsService.getEmbeddingModels().pipe(
            tap((models) => {
                this.modelsSignal.set(models);
                this.allModelsLoadedSignal.set(true);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    createModel(data: CreateEmbeddingModelRequest): Observable<EmbeddingModel> {
        return this.embeddingModelsService.createModel(data).pipe(
            tap((model) => this.upsertModelInCache(model)),
            catchError((err) => throwError(() => err))
        );
    }

    patchModel(id: number, data: Partial<EmbeddingModel>): Observable<EmbeddingModel> {
        return this.embeddingModelsService.patchModel(id, data).pipe(
            tap((model) => this.upsertModelInCache(model)),
            catchError((err) => throwError(() => err))
        );
    }

    deleteModel(id: number): Observable<void> {
        return this.embeddingModelsService.deleteModel(id).pipe(
            tap(() => this.removeModelFromCache(id)),
            catchError((err) => throwError(() => err))
        );
    }

    private upsertModelInCache(model: EmbeddingModel): void {
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
