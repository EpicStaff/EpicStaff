import { inject, Injectable, signal } from '@angular/core';
import { CreateRealtimeModel, RealtimeModel } from '@shared/models';
import { catchError, Observable, of, tap, throwError } from 'rxjs';

import { RealtimeModelsService } from './real-time-models.service';

@Injectable({
    providedIn: 'root',
})
export class RealtimeModelsStorageService {
    private readonly realtimeModelsService = inject(RealtimeModelsService);

    private modelsSignal = signal<RealtimeModel[]>([]);
    private allModelsLoadedSignal = signal<boolean>(false);

    public readonly models = this.modelsSignal.asReadonly();

    getModels(forceRefresh = false): Observable<RealtimeModel[]> {
        if (!forceRefresh && this.allModelsLoadedSignal()) {
            return of(this.modelsSignal());
        }

        return this.realtimeModelsService.getAllModels().pipe(
            tap((models) => {
                this.modelsSignal.set(models);
                this.allModelsLoadedSignal.set(true);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    createModel(data: CreateRealtimeModel): Observable<RealtimeModel> {
        return this.realtimeModelsService.createModel(data).pipe(
            tap((model) => this.upsertModelInCache(model)),
            catchError((err) => throwError(() => err))
        );
    }

    patchModel(id: number, data: Partial<CreateRealtimeModel>): Observable<RealtimeModel> {
        return this.realtimeModelsService.patchModel(id, data).pipe(
            tap((model) => this.upsertModelInCache(model)),
            catchError((err) => throwError(() => err))
        );
    }

    private upsertModelInCache(model: RealtimeModel): void {
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
