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

    it('empties every given source with `all: true`, storage included', () => {
        let failedNames: string[] = [];
        service
            .purgeAll(['flow', 'storage'])
            .subscribe((result) => (failedNames = result.failed.map((failure) => failure.name)));

        const flows = httpTesting.expectOne({ method: 'POST', url: `${API_URL}graphs/recycle-bin/purge/` });
        expect(flows.request.body).toEqual({ all: true });
        flows.flush({ purged: [1], failed: [] });
        const files = httpTesting.expectOne({ method: 'POST', url: `${API_URL}storage/recycle-bin/purge/` });
        expect(files.request.body).toEqual({ all: true });
        files.flush({ purged: [], failed: [{ id: 9, name: 'docs/a.txt', message: 'Storage is unreachable.' }] });

        expect(failedNames).toEqual(['docs/a.txt']);
    });

    it('sends nothing for no items', () => {
        let result: unknown;
        service.restoreItems([]).subscribe((value) => (result = value));
        expect(result).toEqual({ restored: [], failed: [] });
    });
});
