import { firstValueFrom, Observable, of } from 'rxjs';

import { CountedPage, fetchAllPages } from './fetch-all-pages.util';

/** A fake endpoint over `items`; records every (limit, offset) it was asked for. */
function endpoint(items: number[], count = items.length) {
    const calls: [number, number][] = [];
    const fetchPage = (limit: number, offset: number): Observable<CountedPage<number>> => {
        calls.push([limit, offset]);
        return of({ count, results: items.slice(offset, offset + limit) });
    };
    return { calls, fetchPage };
}

function range(length: number): number[] {
    return Array.from({ length }, (_, index) => index);
}

describe('fetchAllPages', () => {
    it('makes one request when the first page holds everything', async () => {
        const { calls, fetchPage } = endpoint(range(30));

        expect(await firstValueFrom(fetchAllPages(fetchPage))).toEqual(range(30));
        expect(calls).toEqual([[100, 0]]);
    });

    it('follows the offset until it has every item, in order', async () => {
        const { calls, fetchPage } = endpoint(range(250));

        expect(await firstValueFrom(fetchAllPages(fetchPage))).toEqual(range(250));
        expect(calls).toEqual([
            [100, 0],
            [100, 100],
            [100, 200],
        ]);
    });

    it('returns an empty list for an empty endpoint, after one request', async () => {
        const { calls, fetchPage } = endpoint([]);

        expect(await firstValueFrom(fetchAllPages(fetchPage))).toEqual([]);
        expect(calls).toEqual([[100, 0]]);
    });

    it('stops at an empty page even when the count promised more (the list shrank meanwhile)', async () => {
        const { calls, fetchPage } = endpoint(range(100), 150);

        expect(await firstValueFrom(fetchAllPages(fetchPage))).toEqual(range(100));
        expect(calls).toEqual([
            [100, 0],
            [100, 100],
        ]);
    });
});
