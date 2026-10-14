import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
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

    function page<Entry>(results: Entry[], count = results.length) {
        return { count, next: null, previous: null, results };
    }

    it('pages a resource bin, with keys that keep equal ids of different bins apart', () => {
        service.load('mcp_tool', { page: 2 }).subscribe();
        httpTesting
            .expectOne(`${API_URL}mcp-tools/recycle-bin/?limit=50&offset=50&ordering=-deleted_at`)
            .flush(page([entry(5, '2026-10-02T10:00:00Z')], 51));

        expect(service.items().map((item) => item.key)).toEqual(['mcp_tool-5']);
        expect(service.page()).toEqual({ current: 2, size: 50, totalCount: 51 });
    });

    it('fails when the bin fails to load', () => {
        service.load('python_tool').subscribe({ error: () => undefined });
        httpTesting
            .expectOne(`${API_URL}python-code-tool/recycle-bin/?limit=50&offset=0&ordering=-deleted_at`)
            .flush(null, { status: 500, statusText: 'Server Error' });

        expect(service.status()).toBe('error');
    });

    it('shows loading only until the first load, even when a reload comes back empty', () => {
        const flowsList = `${API_URL}graphs/recycle-bin/?limit=50&offset=0&ordering=-deleted_at`;
        service.load('flow').subscribe();
        expect(service.status()).toBe('loading');
        httpTesting.expectOne(flowsList).flush(page([entry(1, '2026-10-01T10:00:00Z')]));

        service.load('flow').subscribe();
        expect(service.status()).toBe('loaded');
        httpTesting.expectOne(flowsList).flush(page([]));

        // A search that matched nothing: the next load keeps the table, no spinner.
        service.load('flow').subscribe();
        expect(service.status()).toBe('loaded');
        httpTesting.expectOne(flowsList).flush(page([]));
    });

    it('pages the Files list and keeps the backend order', () => {
        service.load('storage', { page: 2 }).subscribe();
        httpTesting
            .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=50&ordering=-deleted_at`)
            .flush(page([storageEntry(3), storageEntry(8)], 120));

        expect(service.items().map((item) => item.id)).toEqual([3, 8]);
        expect(service.page()).toEqual({ current: 2, size: 50, totalCount: 120 });
    });

    it('reloads the page shown when no page is given', () => {
        service.load('flow', { page: 2 }).subscribe();
        httpTesting
            .expectOne(`${API_URL}graphs/recycle-bin/?limit=50&offset=50&ordering=-deleted_at`)
            .flush(page([entry(1, '2026-10-01T10:00:00Z')], 51));

        service.load('flow').subscribe();
        httpTesting
            .expectOne(`${API_URL}graphs/recycle-bin/?limit=50&offset=50&ordering=-deleted_at`)
            .flush(page([entry(1, '2026-10-01T10:00:00Z')], 51));
    });

    it('steps back to the last page when a reload finds the shown page emptied', () => {
        service.load('secret', { page: 3 }).subscribe();
        httpTesting
            .expectOne(`${API_URL}secrets/recycle-bin/?limit=50&offset=100&ordering=-deleted_at`)
            .flush(page([], 100));
        httpTesting
            .expectOne(`${API_URL}secrets/recycle-bin/?limit=50&offset=50&ordering=-deleted_at`)
            .flush(page([entry(1, '2026-10-01T10:00:00Z')], 100));

        expect(service.page()).toEqual({ current: 2, size: 50, totalCount: 100 });
    });

    it('passes the search, ordering and count filter of a resource bin, but never the item type', () => {
        service
            .load('flow', {
                page: 1,
                query: { search: 'rep', ordering: 'days_left', contents: 'none', itemType: 'file' },
            })
            .subscribe();
        httpTesting
            .expectOne(`${API_URL}graphs/recycle-bin/?limit=50&offset=0&ordering=days_left&search=rep&contents=none`)
            .flush(page([]));
    });

    it('passes the search, ordering and item type of the Files list to the server', () => {
        service
            .load('storage', {
                page: 1,
                query: { search: 'rep', ordering: 'deleted_at', contents: null, itemType: 'file' },
            })
            .subscribe();
        httpTesting
            .expectOne(`${API_URL}storage/recycle-bin/?limit=50&offset=0&ordering=deleted_at&search=rep&item_type=file`)
            .flush(page([]));
    });
});
