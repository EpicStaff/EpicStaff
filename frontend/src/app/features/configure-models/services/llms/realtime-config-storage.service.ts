import { inject, Injectable, signal } from '@angular/core';
import {
    CreateRealtimeModelConfigRequest,
    RealtimeModelConfig,
    UpdateRealtimeModelConfigRequest,
} from '@shared/models';
import { RealtimeModelConfigsService } from '@shared/services';
import { catchError, finalize, Observable, of, tap, throwError } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

@Injectable({
    providedIn: 'root',
})
export class RealtimeConfigStorageService {
    private readonly realtimeModelConfigsService = inject(RealtimeModelConfigsService);

    private configsRequest$?: Observable<RealtimeModelConfig[]>;

    private configsSignal = signal<RealtimeModelConfig[]>([]);
    private configsLoaded = signal<boolean>(false);

    public readonly configs = this.configsSignal.asReadonly();
    public readonly isConfigsLoaded = this.configsLoaded.asReadonly();

    getAllConfigs(forceRefresh = false): Observable<RealtimeModelConfig[]> {
        if (this.configsLoaded() && !forceRefresh) {
            return of(this.configsSignal());
        }

        if (this.configsRequest$ && !forceRefresh) {
            return this.configsRequest$;
        }

        this.configsRequest$ = this.realtimeModelConfigsService.getAllConfigs().pipe(
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

    getConfigById(id: number): Observable<RealtimeModelConfig> {
        const cached = this.configsSignal().find((c) => c.id === id);
        if (cached) {
            return of(cached);
        }
        return this.realtimeModelConfigsService.getConfigById(id).pipe(
            tap((config) => this.mergeConfigsIntoCache([config])),
            catchError((err) => throwError(() => err))
        );
    }

    createConfig(data: CreateRealtimeModelConfigRequest): Observable<RealtimeModelConfig> {
        return this.realtimeModelConfigsService.createConfig(data).pipe(
            tap((config) => {
                this.configsSignal.update((configs) => [config, ...configs]);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    updateConfig(data: UpdateRealtimeModelConfigRequest): Observable<RealtimeModelConfig> {
        return this.realtimeModelConfigsService.updateConfig(data).pipe(
            tap((updated) => this.updateConfigInCache(updated)),
            catchError((err) => throwError(() => err))
        );
    }

    deleteConfig(id: number): Observable<void> {
        return this.realtimeModelConfigsService.deleteConfig(id).pipe(
            tap(() => {
                this.configsSignal.update((configs) => configs.filter((c) => c.id !== id));
            }),
            catchError((err) => throwError(() => err))
        );
    }

    markConfigsOutdated(): void {
        this.configsLoaded.set(false);
    }

    private mergeConfigsIntoCache(incoming: RealtimeModelConfig[]): void {
        this.configsSignal.update((current) => {
            const map = new Map(current.map((c) => [c.id, c]));
            for (const config of incoming) {
                map.set(config.id, config);
            }
            return Array.from(map.values());
        });
    }

    private updateConfigInCache(updated: RealtimeModelConfig): void {
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
