import { inject, Injectable } from '@angular/core';
import { concat, EMPTY, expand, map, Observable, of, tap, toArray } from 'rxjs';

import { RECYCLE_BIN_BULK_ID_LIMIT } from '../constants/recycle-bin-sources.constants';
import {
    RecycleBinBulkFailureResponse,
    RecycleBinBulkPurgeResponse,
    RecycleBinBulkRestoreResponse,
    RecycleBinEmptyResponse,
    RecycleBinFailure,
    RecycleBinItem,
    RecycleBinPurgeResult,
    RecycleBinRestoreResult,
    RecycleBinSelection,
    RecycleBinSourceKey,
} from '../models/recycle-bin.model';
import { toRestoreOutcome } from '../utils/recycle-bin-mappers.util';
import { RecycleBinApiService } from './recycle-bin-api.service';

interface BulkCall {
    source: RecycleBinSourceKey;
    selection: RecycleBinSelection;
}

/**
 * Restores or purges several bin items, possibly from several sources (Tools holds Python and MCP
 * tools). Stateless: the tab and the page both use it.
 *
 * Calls run one after another, never in parallel: per source, ids in chunks of at most 100.
 * The backend reports each skipped item in `failed` and goes on with the rest; the results of all
 * calls are merged into one.
 */
@Injectable({ providedIn: 'root' })
export class RecycleBinBulkService {
    private readonly api = inject(RecycleBinApiService);

    restoreItems(items: readonly RecycleBinItem[]): Observable<RecycleBinRestoreResult> {
        return this.restore(callsForItems(items));
    }

    purgeItems(items: readonly RecycleBinItem[]): Observable<RecycleBinPurgeResult> {
        return this.purge(callsForItems(items));
    }

    /**
     * Everything in every bin the user may delete in, whatever the lists show. Each request
     * purges for a limited time, so a large bin takes several: it calls again while items remain
     * and the last call got somewhere (failed items stay, and are tried again only once).
     */
    emptyAll(onRemaining?: (remaining: number) => void): Observable<RecycleBinPurgeResult> {
        return this.api.emptyAll().pipe(
            expand((response) => (response.remaining > 0 && response.purged_count > 0 ? this.api.emptyAll() : EMPTY)),
            tap((response) => onRemaining?.(response.remaining)),
            toArray(),
            map((responses) => {
                // A failed item is tried again by the next call: keep its last answer only.
                const failures = new Map<string, RecycleBinEmptyResponse['failed'][number]>();
                for (const failure of responses.flatMap((response) => response.failed)) {
                    failures.set(`${failure.source}:${failure.id}`, failure);
                }
                return {
                    purgedCount: responses.reduce((total, response) => total + response.purged_count, 0),
                    failed: [...failures.values()].map(toFailure),
                };
            })
        );
    }

    private restore(calls: BulkCall[]): Observable<RecycleBinRestoreResult> {
        if (calls.length === 0) return of({ restored: [], failed: [] });
        return concat(...calls.map((call) => this.api.restore(call.source, call.selection))).pipe(
            toArray(),
            map((responses: RecycleBinBulkRestoreResponse[]) => ({
                restored: responses.flatMap((response) => response.restored.map(toRestoreOutcome)),
                failed: responses.flatMap((response) => response.failed.map(toFailure)),
            }))
        );
    }

    private purge(calls: BulkCall[]): Observable<RecycleBinPurgeResult> {
        if (calls.length === 0) return of({ purgedCount: 0, failed: [] });
        return concat(...calls.map((call) => this.api.purge(call.source, call.selection))).pipe(
            toArray(),
            map((responses: RecycleBinBulkPurgeResponse[]) => ({
                purgedCount: responses.reduce((total, response) => total + response.purged.length, 0),
                failed: responses.flatMap((response) => response.failed.map(toFailure)),
            }))
        );
    }
}

/** One call per source and chunk of ids, in the items' order. */
function callsForItems(items: readonly RecycleBinItem[]): BulkCall[] {
    const idsBySource = new Map<RecycleBinSourceKey, number[]>();
    for (const item of items) {
        const ids = idsBySource.get(item.source) ?? [];
        ids.push(item.id);
        idsBySource.set(item.source, ids);
    }
    const calls: BulkCall[] = [];
    for (const [source, ids] of idsBySource) {
        for (let start = 0; start < ids.length; start += RECYCLE_BIN_BULK_ID_LIMIT) {
            calls.push({ source, selection: { ids: ids.slice(start, start + RECYCLE_BIN_BULK_ID_LIMIT) } });
        }
    }
    return calls;
}

function toFailure(failure: RecycleBinBulkFailureResponse): RecycleBinFailure {
    return { name: failure.name, message: failure.message };
}
