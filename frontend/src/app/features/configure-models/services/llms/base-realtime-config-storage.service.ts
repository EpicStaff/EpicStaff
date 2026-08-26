import { signal } from '@angular/core';
import { catchError, finalize, Observable, of, tap, throwError } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

export interface RealtimeConfigApi<T, C, U> {
    getAll(): Observable<T[]>;
    create(data: C): Observable<T>;
    update(data: U): Observable<T>;
    delete(id: number): Observable<void>;
}

export abstract class BaseRealtimeConfigStorageService<T extends { id: number }, C, U extends { id: number }> {
    protected abstract readonly api: RealtimeConfigApi<T, C, U>;

    private configsRequest$?: Observable<T[]>;
    private readonly configsSignal = signal<T[]>([]);
    private readonly configsLoaded = signal<boolean>(false);

    public readonly configs = this.configsSignal.asReadonly();
    public readonly isConfigsLoaded = this.configsLoaded.asReadonly();

    getAllConfigs(forceRefresh = false): Observable<T[]> {
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

    createConfig(data: C): Observable<T> {
        return this.api.create(data).pipe(
            tap((config) => this.configsSignal.update((configs) => [config, ...configs])),
            catchError((err) => throwError(() => err))
        );
    }

    updateConfig(data: U): Observable<T> {
        return this.api.update(data).pipe(
            tap((updated) =>
                this.configsSignal.update((configs) => {
                    const i = configs.findIndex((c) => c.id === updated.id);
                    if (i >= 0) {
                        const copy = [...configs];
                        copy[i] = updated;
                        return copy;
                    }
                    return [updated, ...configs];
                })
            ),
            catchError((err) => throwError(() => err))
        );
    }

    deleteConfig(id: number): Observable<void> {
        return this.api.delete(id).pipe(
            tap(() => this.configsSignal.update((configs) => configs.filter((c) => c.id !== id))),
            catchError((err) => throwError(() => err))
        );
    }

    markConfigsOutdated(): void {
        this.configsLoaded.set(false);
    }
}
