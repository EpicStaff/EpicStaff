import { inject, Injectable, signal } from '@angular/core';
import { CreateRealtimeTranscriptionModelRequest, GetRealtimeTranscriptionModelRequest } from '@shared/models';
import { catchError, Observable, of, tap, throwError } from 'rxjs';
import { map } from 'rxjs/operators';

import { RealtimeTranscriptionModelsService } from './transcription-models.service';

@Injectable({
    providedIn: 'root',
})
export class TranscriptionModelsStorageService {
    private readonly transcriptionModelsService = inject(RealtimeTranscriptionModelsService);

    private modelsSignal = signal<GetRealtimeTranscriptionModelRequest[]>([]);
    private allModelsLoadedSignal = signal<boolean>(false);

    public readonly models = this.modelsSignal.asReadonly();

    getModels(forceRefresh = false): Observable<GetRealtimeTranscriptionModelRequest[]> {
        if (!forceRefresh && this.allModelsLoadedSignal()) {
            return of(this.modelsSignal());
        }

        return this.transcriptionModelsService.getAllModels().pipe(
            map((response) => response.results),
            tap((models) => {
                this.modelsSignal.set(models);
                this.allModelsLoadedSignal.set(true);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    createModel(data: CreateRealtimeTranscriptionModelRequest): Observable<GetRealtimeTranscriptionModelRequest> {
        return this.transcriptionModelsService.createModel(data).pipe(
            tap((model) => this.upsertModelInCache(model)),
            catchError((err) => throwError(() => err))
        );
    }

    patchModel(
        id: number,
        data: Partial<CreateRealtimeTranscriptionModelRequest>
    ): Observable<GetRealtimeTranscriptionModelRequest> {
        return this.transcriptionModelsService.patchModel(id, data).pipe(
            tap((model) => this.upsertModelInCache(model)),
            catchError((err) => throwError(() => err))
        );
    }

    private upsertModelInCache(model: GetRealtimeTranscriptionModelRequest): void {
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
