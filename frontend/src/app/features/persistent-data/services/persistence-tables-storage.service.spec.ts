import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { PersistenceTable } from '../models/persistence-table.model';
import { PersistenceTablesApiService } from './persistence-tables-api.service';
import { PersistenceTablesStorageService } from './persistence-tables-storage.service';

describe('PersistenceTablesStorageService', () => {
    let service: PersistenceTablesStorageService;
    let apiService: { getTables: ReturnType<typeof vi.fn> };

    beforeEach(() => {
        apiService = { getTables: vi.fn() };

        TestBed.configureTestingModule({
            providers: [
                {
                    provide: PersistenceTablesApiService,
                    useValue: apiService as unknown as PersistenceTablesApiService,
                },
            ],
        });

        service = TestBed.inject(PersistenceTablesStorageService);
    });

    it('loads tables and caches them in the tables signal', () => {
        const tables: PersistenceTable[] = [
            { id: 1, name: 'Customers', description: '', entry_count: 0, created_at: '', updated_at: '' },
        ];
        apiService.getTables.mockReturnValue(of(tables));

        service.loadTables().subscribe();

        expect(service.tables().map((t) => t.name)).toEqual(['Customers']);
    });

    it('empties the tables signal on clear (org switch / logout)', () => {
        const tables: PersistenceTable[] = [
            { id: 1, name: 'Customers', description: '', entry_count: 0, created_at: '', updated_at: '' },
        ];
        apiService.getTables.mockReturnValue(of(tables));
        service.loadTables().subscribe();
        expect(service.tables().length).toBe(1);

        service.clear();

        expect(service.tables()).toEqual([]);
    });
});
