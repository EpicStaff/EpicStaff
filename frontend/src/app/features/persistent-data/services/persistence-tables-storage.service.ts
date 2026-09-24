import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { Observable, tap } from 'rxjs';

import { PersistenceTable } from '../models/persistence-table.model';
import { PersistenceTablesApiService } from './persistence-tables-api.service';

@Injectable({ providedIn: 'root' })
export class PersistenceTablesStorageService implements StorageService {
    private readonly persistenceTablesApiService = inject(PersistenceTablesApiService);

    private readonly tablesSignal = signal<PersistenceTable[]>([]);
    public readonly tables = this.tablesSignal.asReadonly();

    private readonly refreshTickSignal = signal(0);
    public readonly refreshTick = this.refreshTickSignal.asReadonly();

    triggerRefresh(): void {
        this.refreshTickSignal.update((tick) => tick + 1);
    }

    /** Fetches persistence tables fresh and publishes them into the shared `tables` signal. */
    loadTables(): Observable<PersistenceTable[]> {
        return this.persistenceTablesApiService.getTables().pipe(tap((tables) => this.tablesSignal.set(tables)));
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
