import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { finalize, Observable, shareReplay, tap } from 'rxjs';

import { KeyValueTable } from '../models/key-value-table.model';
import { KeyValueTablesApiService } from './key-value-tables-api.service';

@Injectable({ providedIn: 'root' })
export class KeyValueTablesStorageService implements StorageService {
    private readonly keyValueTablesApiService = inject(KeyValueTablesApiService);

    private readonly tablesSignal = signal<KeyValueTable[]>([]);
    public readonly tables = this.tablesSignal.asReadonly();

    private readonly refreshTickSignal = signal(0);
    public readonly refreshTick = this.refreshTickSignal.asReadonly();

    // ponytail: one in-flight request shared by all callers, not per-caller dedup. Fine while
    // the only concurrent callers are canvas nodes loading on init; revisit if load() grows params.
    private inFlightLoad: Observable<KeyValueTable[]> | null = null;
    // Generation of the request currently held in `inFlightLoad`; lets a stale `finalize` tell
    // it no longer owns `inFlightLoad` (a `clear()` handed it to a newer request) and skip the reset.
    private inFlightGeneration = -1;
    // Bumped by `clear()` (org switch / logout). A response tags itself with the generation that
    // was current when its request started; if `clear()` ran meanwhile, the tag no longer matches
    // and the response is dropped instead of overwriting the new org's `tables` signal.
    private loadGeneration = 0;

    triggerRefresh(): void {
        this.refreshTickSignal.update((tick) => tick + 1);
    }

    /** Fetches key-value tables fresh and publishes them into the shared `tables` signal.
     *  Concurrent callers (e.g. several Key-Value nodes on the same canvas initializing at
     *  once) share a single in-flight HTTP request instead of each firing their own. A response
     *  that arrives after a `clear()` (org switch) is dropped rather than overwriting the new
     *  org's tables — see `loadGeneration`. */
    loadTables(): Observable<KeyValueTable[]> {
        if (this.inFlightLoad) {
            return this.inFlightLoad;
        }
        const generation = this.loadGeneration;
        const request$ = this.keyValueTablesApiService.getTables().pipe(
            tap((tables) => {
                if (generation === this.loadGeneration) {
                    this.tablesSignal.set(tables);
                }
            }),
            finalize(() => {
                if (this.inFlightGeneration === generation) {
                    this.inFlightLoad = null;
                }
            }),
            shareReplay(1)
        );
        this.inFlightLoad = request$;
        this.inFlightGeneration = generation;
        return request$;
    }

    /** For callers that just changed the tables (create, rename, delete): unlike `loadTables()`,
     *  never joins a load already in flight, which may have started before the change. Moving
     *  `loadGeneration` on makes that load's late response a stale one, so its `tap` drops it and
     *  its `finalize` leaves the new `inFlightLoad` alone (see `loadGeneration`, `inFlightGeneration`). */
    reloadTables(): Observable<KeyValueTable[]> {
        this.loadGeneration++;
        this.inFlightLoad = null;
        return this.loadTables();
    }

    /** Resets the cache on org switch / logout (`AppStorageService.clearAll`, registered via
     *  `provideKeyValueTablesStorages`) so a newly-active org never keeps showing the previous
     *  org's key-value tables. Bumps `refreshTick` (not reset to 0) so any effect watching it
     *  for a change always fires, even when the tick already happened to be 0. Also bumps
     *  `loadGeneration` so a load already in flight can no longer write its (other org's)
     *  response into `tables`, and drops `inFlightLoad` so the next `loadTables()` call fires a
     *  fresh request under the new org instead of returning the old org's shared observable. */
    clear(): void {
        this.loadGeneration++;
        this.inFlightLoad = null;
        this.tablesSignal.set([]);
        this.triggerRefresh();
    }
}
