import { inject, Injectable, signal } from '@angular/core';
import { map, Observable, of, switchMap, tap } from 'rxjs';

import { RECYCLE_BIN_PAGE_SIZE } from '../constants/recycle-bin-sources.constants';
import {
    RecycleBinItem,
    RecycleBinListQuery,
    RecycleBinLoadStatus,
    RecycleBinPage,
    RecycleBinSourceKey,
} from '../models/recycle-bin.model';
import { toContents, toRecycleBinItem, toStorageRecycleBinItem } from '../utils/recycle-bin-mappers.util';
import { DEFAULT_LIST_QUERY } from '../utils/recycle-bin-query.util';
import { RecycleBinApiService } from './recycle-bin-api.service';

export interface RecycleBinLoadOptions {
    /** The page to load (1-based); by default the page already shown. */
    page?: number;
    /** Search, ordering and filters, all applied by the server. */
    query?: RecycleBinListQuery;
}

interface PageResult {
    items: RecycleBinItem[];
    page: RecycleBinPage;
}

/** One page of a bin, before it is turned into a PageResult. */
interface FetchedPage {
    items: RecycleBinItem[];
    totalCount: number;
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
    /** Paging of the list; `null` until the first page has loaded. */
    readonly page = this.pageSignal.asReadonly();

    /**
     * Fetch one page of `source` with the given query, in the backend's order. Shows 'loading' only
     * until the first load succeeds: a reload (after an action, or a search that matched nothing)
     * keeps the table instead of flashing the spinner.
     */
    load(source: RecycleBinSourceKey, options: RecycleBinLoadOptions = {}): Observable<RecycleBinItem[]> {
        const pageNumber = options.page ?? this.pageSignal()?.current ?? 1;
        const query = options.query ?? DEFAULT_LIST_QUERY;
        if (this.statusSignal() !== 'loaded') this.statusSignal.set('loading');
        return this.fetchPage(source, pageNumber, query).pipe(
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

    private fetchPage(
        source: RecycleBinSourceKey,
        pageNumber: number,
        query: RecycleBinListQuery
    ): Observable<PageResult> {
        const size = RECYCLE_BIN_PAGE_SIZE;
        return this.fetchEntries(source, size, (pageNumber - 1) * size, query).pipe(
            switchMap(({ items, totalCount }) => {
                const lastPage = Math.max(1, Math.ceil(totalCount / size));
                // A restore or purge emptied the last page: show the page that is now last.
                if (items.length === 0 && pageNumber > lastPage) {
                    return this.fetchPage(source, lastPage, query);
                }
                return of({ items, page: { current: pageNumber, size, totalCount } });
            })
        );
    }

    private fetchEntries(
        source: RecycleBinSourceKey,
        limit: number,
        offset: number,
        query: RecycleBinListQuery
    ): Observable<FetchedPage> {
        if (source === 'storage') {
            return this.api.getStorageEntries(limit, offset, query).pipe(
                map((response) => ({
                    items: response.results.map(toStorageRecycleBinItem),
                    totalCount: response.count,
                }))
            );
        }
        return this.api.getEntries(source, limit, offset, query).pipe(
            map((response) => ({
                items: response.results.map((entry) => toRecycleBinItem(source, entry)),
                totalCount: response.count,
            }))
        );
    }
}
