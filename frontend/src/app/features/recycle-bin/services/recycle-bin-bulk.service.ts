import { inject, Injectable } from '@angular/core';
import { concat, map, Observable, of, toArray } from 'rxjs';

import { RECYCLE_BIN_BULK_ID_LIMIT } from '../constants/recycle-bin-sources.constants';
import {
    RecycleBinBulkFailureResponse,
    RecycleBinBulkPurgeResponse,
    RecycleBinBulkRestoreResponse,
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

    /** Everything in the bin of each source, whatever the list shows (search and paging aside). */
    purgeAll(sources: readonly RecycleBinSourceKey[]): Observable<RecycleBinPurgeResult> {
        return this.purge(sources.map((source) => ({ source, selection: { all: true } })));
    }

    private restore(calls: BulkCall[]): Observable<RecycleBinRestoreResult> {
        if (calls.length === 0) return of({ restored: [], failed: [] });
        return concat(...calls.map((call) => this.api.restore(call.source, call.selection))).pipe(
            toArray(),
            map((responses: RecycleBinBulkRestoreResponse[]) => ({
                // concat keeps the calls' order: response `index` answers calls[index].
                restored: responses.flatMap((response, index) =>
                    response.restored.map((item) => toRestoreOutcome(calls[index].source, item))
                ),
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
