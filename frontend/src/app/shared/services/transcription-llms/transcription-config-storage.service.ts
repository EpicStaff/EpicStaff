import { inject, Injectable, signal } from '@angular/core';
import {
    CreateTranscriptionConfigRequest,
    GetTranscriptionConfigRequest,
    UpdateTranscriptionConfigRequest,
} from '@shared/models';
import { catchError, finalize, Observable, of, tap, throwError } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

import { TranscriptionConfigsService } from './transcription-config.service';

@Injectable({
    providedIn: 'root',
})
export class TranscriptionConfigStorageService {
    private readonly transcriptionConfigsService = inject(TranscriptionConfigsService);

    private configsRequest$?: Observable<GetTranscriptionConfigRequest[]>;

    private configsSignal = signal<GetTranscriptionConfigRequest[]>([]);
    private configsLoaded = signal<boolean>(false);

    public readonly configs = this.configsSignal.asReadonly();
    public readonly isConfigsLoaded = this.configsLoaded.asReadonly();

    getAllConfigs(forceRefresh = false): Observable<GetTranscriptionConfigRequest[]> {
        if (this.configsLoaded() && !forceRefresh) {
            return of(this.configsSignal());
        }

        if (this.configsRequest$ && !forceRefresh) {
            return this.configsRequest$;
        }

        this.configsRequest$ = this.transcriptionConfigsService.getTranscriptionConfigs().pipe(
            tap((configs) => {
                this.configsSignal.set(configs);
                this.configsLoaded.set(true);
            }),
            finalize(() => {
                this.configsRequest$ = undefined;
            }),
            shareReplay(1)
        );

        return this.configsRequest$;
    }

    getConfigById(id: number): Observable<GetTranscriptionConfigRequest> {
        const cached = this.configsSignal().find((c) => c.id === id);
        if (cached) {
            return of(cached);
        }
        return this.transcriptionConfigsService.getTranscriptionConfigById(id).pipe(
            tap((config) => this.mergeConfigsIntoCache([config])),
            catchError((err) => throwError(() => err))
        );
    }

    createConfig(data: CreateTranscriptionConfigRequest): Observable<GetTranscriptionConfigRequest> {
        return this.transcriptionConfigsService.createTranscriptionConfig(data).pipe(
            tap((config) => {
                this.configsSignal.update((configs) => [config, ...configs]);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    updateConfig(data: UpdateTranscriptionConfigRequest): Observable<GetTranscriptionConfigRequest> {
        return this.transcriptionConfigsService.updateTranscriptionConfig(data).pipe(
            tap((updated) => this.updateConfigInCache(updated)),
            catchError((err) => throwError(() => err))
        );
    }

    deleteConfig(id: number): Observable<void> {
        return this.transcriptionConfigsService.deleteTranscriptionConfig(id).pipe(
            tap(() => {
                this.configsSignal.update((configs) => configs.filter((c) => c.id !== id));
            }),
            catchError((err) => throwError(() => err))
        );
    }

    markConfigsOutdated(): void {
        this.configsLoaded.set(false);
    }

    private mergeConfigsIntoCache(incoming: GetTranscriptionConfigRequest[]): void {
        this.configsSignal.update((current) => {
            const map = new Map(current.map((c) => [c.id, c]));
            for (const config of incoming) {
                map.set(config.id, config);
            }
            return Array.from(map.values());
        });
    }

    private updateConfigInCache(updated: GetTranscriptionConfigRequest): void {
        this.configsSignal.update((configs) => {
            const index = configs.findIndex((c) => c.id === updated.id);
            if (index >= 0) {
                const copy = [...configs];
                copy[index] = updated;
                return copy;
            }
            return [updated, ...configs];
        });
    }
}
