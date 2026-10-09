import { inject, Injectable, signal } from '@angular/core';
import { forkJoin, map, Observable, of, switchMap, tap } from 'rxjs';

import { RECYCLE_BIN_STORAGE_PAGE_SIZE } from '../constants/recycle-bin-sources.constants';
import {
    RecycleBinItem,
    RecycleBinLoadStatus,
    RecycleBinPage,
    RecycleBinSourceKey,
    RecycleBinStorageQuery,
    RecycleBinTabDefinition,
} from '../models/recycle-bin.model';
import { newestFirst, toContents, toRecycleBinItem, toStorageRecycleBinItem } from '../utils/recycle-bin-mappers.util';
import { DEFAULT_STORAGE_QUERY } from '../utils/recycle-bin-query.util';
import { RecycleBinApiService } from './recycle-bin-api.service';

export interface RecycleBinLoadOptions {
    /** A paged source's page (1-based); by default the page already shown. */
    page?: number;
    /** Search and ordering of the paged Files list; the other lists are filtered and sorted on the client. */
    storageQuery?: RecycleBinStorageQuery;
}

interface SourceResult {
    items: RecycleBinItem[];
    /** Set only for a paged source (storage). */
    page: RecycleBinPage | null;
}

/** State of one bin tab. Provided by RecycleBinTabComponent, so every tab starts empty. */
@Injectable()
export class RecycleBinStorageService {
    private readonly api = inject(RecycleBinApiService);
    private readonly itemsSignal = signal<RecycleBinItem[]>([]);
    private readonly statusSignal = signal<RecycleBinLoadStatus>('loading');
    private readonly pageSignal = signal<RecycleBinPage | null>(null);

    readonly items = this.itemsSignal.asReadonly();
    readonly status = this.statusSignal.asReadonly();
    /** Paging of the list; `null` for a tab whose lists aren't paged. */
    readonly page = this.pageSignal.asReadonly();

    /**
     * Fetch every source of `tab`; several sources are merged newest first. A paged source
     * (Files) fetches one page with the given query. Shows 'loading' only until the first load
     * succeeds: a reload (after an action, or a search that matched nothing) keeps the table
     * instead of flashing the spinner.
     */
    load(tab: RecycleBinTabDefinition, options: RecycleBinLoadOptions = {}): Observable<RecycleBinItem[]> {
        const pageNumber = options.page ?? this.pageSignal()?.current ?? 1;
        const storageQuery = options.storageQuery ?? DEFAULT_STORAGE_QUERY;
        if (this.statusSignal() !== 'loaded') this.statusSignal.set('loading');
        return forkJoin(tab.sources.map((source) => this.fetchSource(source, pageNumber, storageQuery))).pipe(
            map((results) => {
                const items = results.flatMap((result) => result.items);
                // One source keeps the backend's order (storage sorts by path within a deletion time).
                return {
                    items: results.length > 1 ? items.sort(newestFirst) : items,
                    page: results.find((result) => result.page !== null)?.page ?? null,
                };
            }),
            tap({
                next: ({ items, page }) => {
                    this.itemsSignal.set(items);
                    this.pageSignal.set(page);
                    this.statusSignal.set('loaded');
                },
                error: () => this.statusSignal.set('error'),
            }),
            map(({ items }) => items)
        );
    }

    /** Replace a row's capped contents with all of them ("Show all"). */
    loadAllContents(item: RecycleBinItem): Observable<void> {
        return this.api.getContents(item.source, item.id).pipe(
            tap((response) =>
                this.itemsSignal.update((items) =>
                    items.map((current) =>
                        current.key === item.key
                            ? {
                                  ...current,
                                  contents: toContents(item.source, response.contents),
                                  contentsTotal: response.contents_total,
                              }
                            : current
                    )
                )
            ),
            map(() => undefined)
        );
    }

    private fetchSource(
        source: RecycleBinSourceKey,
        pageNumber: number,
        storageQuery: RecycleBinStorageQuery
    ): Observable<SourceResult> {
        switch (source) {
            case 'storage':
                return this.fetchStoragePage(pageNumber, storageQuery);
            default:
                return this.api.getEntries(source).pipe(
                    map((entries) => ({
                        items: entries.map((entry) => toRecycleBinItem(source, entry)),
                        page: null,
                    }))
                );
        }
    }

    private fetchStoragePage(pageNumber: number, query: RecycleBinStorageQuery): Observable<SourceResult> {
        const size = RECYCLE_BIN_STORAGE_PAGE_SIZE;
        return this.api.getStorageEntries(size, (pageNumber - 1) * size, query).pipe(
            switchMap((response) => {
                const lastPage = Math.max(1, Math.ceil(response.count / size));
                // A restore or purge emptied the last page: show the page that is now last.
                if (response.results.length === 0 && pageNumber > lastPage) {
                    return this.fetchStoragePage(lastPage, query);
                }
                return of({
                    items: response.results.map(toStorageRecycleBinItem),
                    page: { current: pageNumber, size, totalCount: response.count },
                });
            })
        );
    }
}
