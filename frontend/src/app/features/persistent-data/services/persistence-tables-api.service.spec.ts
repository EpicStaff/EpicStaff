import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { PersistenceTablesApiService } from './persistence-tables-api.service';

describe('PersistenceTablesApiService', () => {
    let service: PersistenceTablesApiService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(PersistenceTablesApiService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('loads tables and caches them in the tables signal', () => {
        service.loadTables().subscribe();
        const request = httpMock.expectOne((r) => r.url === '/api/persistence-tables/');
        request.flush({ count: 1, next: null, previous: null, results: [{ id: 1, name: 'Customers' }] });
        expect(service.tables().map((t) => t.name)).toEqual(['Customers']);
    });

    it('sends table, paging and search params when listing entries', () => {
        service.getEntries({ table: 3, search: 'order', limit: 20, offset: 40 }).subscribe();
        const request = httpMock.expectOne((r) => r.url === '/api/persistence-table-entries/');
        expect(request.request.params.get('table')).toBe('3');
        expect(request.request.params.get('search')).toBe('order');
        expect(request.request.params.get('limit')).toBe('20');
        expect(request.request.params.get('offset')).toBe('40');
        request.flush({ count: 0, next: null, previous: null, results: [] });
    });

    it('omits the search param when empty', () => {
        service.getEntries({ table: 3, search: '', limit: 20, offset: 0 }).subscribe();
        const request = httpMock.expectOne((r) => r.url === '/api/persistence-table-entries/');
        expect(request.request.params.has('search')).toBe(false);
        request.flush({ count: 0, next: null, previous: null, results: [] });
    });

    it('posts keys to the lookup endpoint', () => {
        service.lookupEntries(3, ['a', 'b']).subscribe();
        const request = httpMock.expectOne('/api/persistence-tables/3/entries/lookup/');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({ keys: ['a', 'b'] });
        request.flush({});
    });
});
