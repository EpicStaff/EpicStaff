import { inject, Injectable, signal } from '@angular/core';
import { CreateEmbeddingConfigRequest, EmbeddingConfig, GetEmbeddingConfigRequest } from '@shared/models';
import { EmbeddingConfigsService } from '@shared/services';
import { catchError, finalize, Observable, of, tap, throwError } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

@Injectable({
    providedIn: 'root',
})
export class EmbeddingConfigStorageService {
    private readonly embeddingConfigsService = inject(EmbeddingConfigsService);

    private configsRequest$?: Observable<EmbeddingConfig[]>;

    private configsSignal = signal<EmbeddingConfig[]>([]);
    private configsLoaded = signal<boolean>(false);

    public readonly configs = this.configsSignal.asReadonly();
    public readonly isConfigsLoaded = this.configsLoaded.asReadonly();

    getAllConfigs(forceRefresh = false): Observable<EmbeddingConfig[]> {
        if (this.configsLoaded() && !forceRefresh) {
            return of(this.configsSignal());
        }

        if (this.configsRequest$ && !forceRefresh) {
            return this.configsRequest$;
        }

        this.configsRequest$ = this.embeddingConfigsService.getEmbeddingConfigs().pipe(
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

    getConfigById(id: number): Observable<EmbeddingConfig> {
        const cached = this.configsSignal().find((c) => c.id === id);
        if (cached) {
            return of(cached);
        }
        return this.embeddingConfigsService.getEmbeddingConfigById(id).pipe(
            tap((config) => this.mergeConfigsIntoCache([config])),
            catchError((err) => throwError(() => err))
        );
    }

    createConfig(data: CreateEmbeddingConfigRequest): Observable<GetEmbeddingConfigRequest> {
        return this.embeddingConfigsService.createEmbeddingConfig(data).pipe(
            tap((config) => {
                this.configsSignal.update((configs) => [config, ...configs]);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    updateConfig(data: EmbeddingConfig): Observable<EmbeddingConfig> {
        return this.embeddingConfigsService.updateEmbeddingConfig(data).pipe(
            tap((updated) => this.updateConfigInCache(updated)),
            catchError((err) => throwError(() => err))
        );
    }

    deleteConfig(id: number): Observable<void> {
        return this.embeddingConfigsService.deleteEmbeddingConfig(id).pipe(
            tap(() => {
                this.configsSignal.update((configs) => configs.filter((c) => c.id !== id));
            }),
            catchError((err) => throwError(() => err))
        );
    }

    markConfigsOutdated(): void {
        this.configsLoaded.set(false);
    }

    private mergeConfigsIntoCache(incoming: EmbeddingConfig[]): void {
        this.configsSignal.update((current) => {
            const map = new Map(current.map((c) => [c.id, c]));
            for (const config of incoming) {
                map.set(config.id, config);
            }
            return Array.from(map.values());
        });
    }

    private updateConfigInCache(updated: EmbeddingConfig): void {
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
