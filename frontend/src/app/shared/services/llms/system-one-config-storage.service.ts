import { inject, Injectable, signal } from '@angular/core';
import { BulkDeleteResponse, BulkDeleteTarget, SystemOneConfig, SystemOneConfigWrite } from '@shared/models';
import { finalize, Observable, of, tap } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

import { StorageService } from '../app-storage.service';
import { SystemOneConfigService } from './system-one-config.service';

@Injectable({ providedIn: 'root' })
export class SystemOneConfigStorageService implements StorageService, BulkDeleteTarget {
    private readonly api = inject(SystemOneConfigService);

    private configsRequest$?: Observable<SystemOneConfig[]>;
    private readonly configsSignal = signal<SystemOneConfig[]>([]);
    private readonly configsLoaded = signal<boolean>(false);

    public readonly configs = this.configsSignal.asReadonly();
    public readonly isConfigsLoaded = this.configsLoaded.asReadonly();

    getAllConfigs(forceRefresh = false): Observable<SystemOneConfig[]> {
        if (this.configsLoaded() && !forceRefresh) return of(this.configsSignal());
        if (this.configsRequest$ && !forceRefresh) return this.configsRequest$;

        this.configsRequest$ = this.api.getAll().pipe(
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

    createConfig(data: SystemOneConfigWrite): Observable<SystemOneConfig> {
        return this.api
            .create(data)
            .pipe(tap((config) => this.configsSignal.update((configs) => [config, ...configs])));
    }

    updateConfig(id: number, data: Partial<SystemOneConfigWrite>): Observable<SystemOneConfig> {
        return this.api
            .update(id, data)
            .pipe(
                tap((updated) =>
                    this.configsSignal.update((configs) =>
                        configs.some((config) => config.id === updated.id)
                            ? configs.map((config) => (config.id === updated.id ? updated : config))
                            : [updated, ...configs]
                    )
                )
            );
    }

    previewBulkDelete(ids: number[]): Observable<BulkDeleteResponse> {
        return this.api.bulkDelete(ids, { dryRun: true });
    }

    bulkDelete(ids: number[]): Observable<BulkDeleteResponse> {
        return this.api
            .bulkDelete(ids)
            .pipe(tap((response) => this.removeFromCache([...response.deleted_ids, ...response.not_found_ids])));
    }

    removeFromCache(ids: number[]): void {
        if (ids.length === 0) return;
        const idSet = new Set(ids);
        this.configsSignal.update((configs) => configs.filter((config) => !idSet.has(config.id)));
    }

    clear(): void {
        this.configsSignal.set([]);
        this.configsLoaded.set(false);
        this.configsRequest$ = undefined;
    }
}
