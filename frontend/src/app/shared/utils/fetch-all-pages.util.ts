import { EMPTY, expand, map, Observable, reduce } from 'rxjs';

/** The most a limit/offset list endpoint hands out per request (the backend's `max_limit`). */
export const FETCH_ALL_PAGES_LIMIT = 100;

/** The part of a limit/offset page this helper reads. */
export interface CountedPage<Item> {
    count: number;
    results: Item[];
}

/**
 * Every item of a limit/offset paged list, in order: asks for the first page, then the next offset
 * until it has `count` items. Meant for lists that stay small (a recycle bin, emptied by its retention),
 * so usually one request. An empty page ends it early, so a shrinking list can't loop forever.
 */
export function fetchAllPages<Item>(
    fetchPage: (limit: number, offset: number) => Observable<CountedPage<Item>>,
    limit: number = FETCH_ALL_PAGES_LIMIT
): Observable<Item[]> {
    const fetchFrom = (offset: number): Observable<{ page: CountedPage<Item>; offset: number }> =>
        fetchPage(limit, offset).pipe(map((page) => ({ page, offset })));
    return fetchFrom(0).pipe(
        expand(({ page, offset }) => {
            const nextOffset = offset + page.results.length;
            return page.results.length > 0 && nextOffset < page.count ? fetchFrom(nextOffset) : EMPTY;
        }),
        reduce((items: Item[], { page }) => items.concat(page.results), [])
    );
}
