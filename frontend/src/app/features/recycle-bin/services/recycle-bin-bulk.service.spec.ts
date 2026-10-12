import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { RecycleBinItem, RecycleBinSourceKey } from '../models/recycle-bin.model';
import { RecycleBinBulkService } from './recycle-bin-bulk.service';

const API_URL = 'http://api/';

function binItem(source: RecycleBinSourceKey, id: number): RecycleBinItem {
    return {
        key: `${source}-${id}`,
        id,
        source,
        name: `Item ${id}`,
        displayName: `Item ${id}`,
        kind: '',
        deletedAt: new Date(),
        daysLeft: 5,
        details: [],
        contents: [],
        contentsTotal: 0,
    };
}

describe('RecycleBinBulkService', () => {
    let service: RecycleBinBulkService;
    let httpTesting: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
            ],
        });
        service = TestBed.inject(RecycleBinBulkService);
        httpTesting = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpTesting.verify());

    it('restores items by id, one call per source, and merges the results', () => {
        let restoredNames: string[] = [];
        service
            .restoreItems([binItem('python_tool', 1), binItem('mcp_tool', 2), binItem('python_tool', 3)])
            .subscribe((result) => (restoredNames = result.restored.map((outcome) => outcome.name)));

        const python = httpTesting.expectOne({
            method: 'POST',
            url: `${API_URL}python-code-tool/recycle-bin/restore/`,
        });
        expect(python.request.body).toEqual({ ids: [1, 3] });
        python.flush({
            restored: [
                { id: 1, name: 'A', renamed_from: null },
                { id: 3, name: 'C', renamed_from: null },
            ],
            failed: [],
        });
        const mcp = httpTesting.expectOne({ method: 'POST', url: `${API_URL}mcp-tools/recycle-bin/restore/` });
        expect(mcp.request.body).toEqual({ ids: [2] });
        mcp.flush({ restored: [{ id: 2, name: 'B', renamed_from: null }], failed: [] });

        expect(restoredNames).toEqual(['A', 'C', 'B']);
    });

    it('sends more than 100 ids in chunks of 100, one after another', () => {
        const items = Array.from({ length: 150 }, (_, index) => binItem('flow', index + 1));
        let purgedCount = 0;
        service.purgeItems(items).subscribe((result) => (purgedCount = result.purgedCount));

        const first = httpTesting.expectOne({ method: 'POST', url: `${API_URL}graphs/recycle-bin/purge/` });
        expect(first.request.body.ids).toHaveLength(100);
        first.flush({ purged: first.request.body.ids, failed: [] });
        const second = httpTesting.expectOne({ method: 'POST', url: `${API_URL}graphs/recycle-bin/purge/` });
        expect(second.request.body.ids).toHaveLength(50);
        second.flush({ purged: second.request.body.ids, failed: [] });

        expect(purgedCount).toBe(150);
    });

    it('empties a large bin over several calls, reporting what is left and each failure once', () => {
        const left: number[] = [];
        let result: unknown;
        service.emptyAll((remaining) => left.push(remaining)).subscribe((value) => (result = value));
        const stuck = { source: 'storage', id: 9, name: 'docs/a.txt', message: 'Storage is unreachable.' };
        const answer = (purged_count: number, remaining: number) =>
            httpTesting
                .expectOne({ method: 'POST', url: `${API_URL}recycle-bin/empty/` })
                .flush({ purged_count, failed: [stuck], remaining });

        answer(4, 3);
        answer(2, 1);
        // Only the failed item is left, and this call got nowhere: stop.
        answer(0, 1);

        expect(left).toEqual([3, 1, 1]);
        expect(result).toEqual({
            purgedCount: 6,
            failed: [{ name: 'docs/a.txt', message: 'Storage is unreachable.' }],
        });
    });

    it('sends nothing for no items', () => {
        let result: unknown;
        service.restoreItems([]).subscribe((value) => (result = value));
        expect(result).toEqual({ restored: [], failed: [] });
    });
});
