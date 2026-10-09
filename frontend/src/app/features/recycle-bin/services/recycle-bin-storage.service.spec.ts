import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { RECYCLE_BIN_TAB_BY_KEY } from '../constants/recycle-bin-tabs.constants';
import { GetRecycleBinEntryResponse, GetStorageRecycleBinEntryResponse } from '../models/recycle-bin.model';
import { RecycleBinStorageService } from './recycle-bin-storage.service';

const API_URL = 'http://api/';

function entry(id: number, deletedAt: string): GetRecycleBinEntryResponse {
    return {
        id,
        name: `Item ${id}`,
        deleted_at: deletedAt,
        days_left: 5,
        details: [],
        contents: [],
        contents_total: 0,
    };
}

function storageEntry(id: number): GetStorageRecycleBinEntryResponse {
    return { ...entry(id, '2026-10-01T10:00:00Z'), name: `docs/file-${id}.txt`, item_type: 'file' };
}

describe('RecycleBinStorageService', () => {
    let service: RecycleBinStorageService;
    let httpTesting: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                RecycleBinStorageService,
            ],
        });
        service = TestBed.inject(RecycleBinStorageService);
        httpTesting = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpTesting.verify());

    it('merges Python and MCP tools newest first, with keys that keep equal ids apart', () => {
        service.load(RECYCLE_BIN_TAB_BY_KEY.tools).subscribe();
        httpTesting.expectOne(`${API_URL}python-code-tool/recycle-bin/`).flush([entry(5, '2026-10-01T10:00:00Z')]);
        httpTesting.expectOne(`${API_URL}mcp-tools/recycle-bin/`).flush([entry(5, '2026-10-02T10:00:00Z')]);

        expect(service.items().map((item) => item.key)).toEqual(['mcp_tool-5', 'python_tool-5']);
        expect(service.page()).toBeNull();
    });

    it('fails the Tools tab when one of its two lists fails', () => {
        service.load(RECYCLE_BIN_TAB_BY_KEY.tools).subscribe({ error: () => undefined });
        httpTesting.expectOne(`${API_URL}python-code-tool/recycle-bin/`).flush([]);
        httpTesting
            .expectOne(`${API_URL}mcp-tools/recycle-bin/`)
            .flush(null, { status: 500, statusText: 'Server Error' });

        expect(service.status()).toBe('error');
    });

    it('shows loading only until the first load, even when a reload comes back empty', () => {
        service.load(RECYCLE_BIN_TAB_BY_KEY.flows).subscribe();
        expect(service.status()).toBe('loading');
        httpTesting.expectOne(`${API_URL}graphs/recycle-bin/`).flush([entry(1, '2026-10-01T10:00:00Z')]);

        service.load(RECYCLE_BIN_TAB_BY_KEY.flows).subscribe();
        expect(service.status()).toBe('loaded');
        httpTesting.expectOne(`${API_URL}graphs/recycle-bin/`).flush([]);

        // A search that matched nothing: the next load keeps the table, no spinner.
        service.load(RECYCLE_BIN_TAB_BY_KEY.flows).subscribe();
        expect(service.status()).toBe('loaded');
        httpTesting.expectOne(`${API_URL}graphs/recycle-bin/`).flush([]);
    });

    it('pages the Files list and keeps the backend order', () => {
        service.load(RECYCLE_BIN_TAB_BY_KEY.files, { page: 2 }).subscribe();
        httpTesting
            .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=50&ordering=-deleted_at`)
            .flush({ count: 120, next: null, previous: null, results: [storageEntry(3), storageEntry(8)] });

        expect(service.items().map((item) => item.id)).toEqual([3, 8]);
        expect(service.page()).toEqual({ current: 2, size: 50, totalCount: 120 });
    });

    it('steps back to the last page when a reload finds the shown page emptied', () => {
        service.load(RECYCLE_BIN_TAB_BY_KEY.files, { page: 3 }).subscribe();
        httpTesting
            .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=100&ordering=-deleted_at`)
            .flush({ count: 100, next: null, previous: null, results: [] });
        httpTesting
            .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=50&ordering=-deleted_at`)
            .flush({ count: 100, next: null, previous: null, results: [storageEntry(1)] });

        expect(service.page()).toEqual({ current: 2, size: 50, totalCount: 100 });
    });

    it('passes the search and ordering of the Files list to the server', () => {
        service
            .load(RECYCLE_BIN_TAB_BY_KEY.files, {
                page: 1,
                storageQuery: { search: 'rep', ordering: 'deleted_at', itemType: 'file' },
            })
            .subscribe();
        httpTesting
            .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=0&ordering=deleted_at&search=rep&item_type=file`)
            .flush({ count: 0, next: null, previous: null, results: [] });
    });
});
