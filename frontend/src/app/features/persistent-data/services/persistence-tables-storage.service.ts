import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { finalize, Observable, shareReplay, tap } from 'rxjs';

import { PersistenceTable } from '../models/persistence-table.model';
import { PersistenceTablesApiService } from './persistence-tables-api.service';

@Injectable({ providedIn: 'root' })
export class PersistenceTablesStorageService implements StorageService {
    private readonly persistenceTablesApiService = inject(PersistenceTablesApiService);

    private readonly tablesSignal = signal<PersistenceTable[]>([]);
    public readonly tables = this.tablesSignal.asReadonly();

    private readonly refreshTickSignal = signal(0);
    public readonly refreshTick = this.refreshTickSignal.asReadonly();

    // ponytail: one in-flight request shared by all callers, not per-caller dedup. Fine while
    // the only concurrent callers are canvas nodes loading on init; revisit if load() grows params.
    private inFlightLoad: Observable<PersistenceTable[]> | null = null;

    triggerRefresh(): void {
        this.refreshTickSignal.update((tick) => tick + 1);
    }

    /** Fetches persistence tables fresh and publishes them into the shared `tables` signal.
     *  Concurrent callers (e.g. several persistence nodes on the same canvas initializing at
     *  once) share a single in-flight HTTP request instead of each firing their own. */
    loadTables(): Observable<PersistenceTable[]> {
        if (this.inFlightLoad) {
            return this.inFlightLoad;
        }
        this.inFlightLoad = this.persistenceTablesApiService.getTables().pipe(
            tap((tables) => this.tablesSignal.set(tables)),
            finalize(() => (this.inFlightLoad = null)),
            shareReplay(1)
        );
        return this.inFlightLoad;
    }

    /** Resets the cache on org switch / logout (`AppStorageService.clearAll`, registered via
     *  `providePersistentDataStorages`) so a newly-active org never keeps showing the previous
     *  org's persistence tables. Bumps `refreshTick` (not reset to 0) so any effect watching it
     *  for a change always fires, even when the tick already happened to be 0. */
    clear(): void {
        this.tablesSignal.set([]);
        this.triggerRefresh();
    }
}
