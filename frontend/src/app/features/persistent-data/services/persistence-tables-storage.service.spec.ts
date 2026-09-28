import { TestBed } from '@angular/core/testing';
import { of, Subject } from 'rxjs';

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

    it('shares one in-flight request across concurrent callers (e.g. several canvas nodes)', () => {
        const tables: PersistenceTable[] = [
            { id: 1, name: 'Customers', description: '', entry_count: 0, created_at: '', updated_at: '' },
        ];
        const response$ = new Subject<PersistenceTable[]>();
        apiService.getTables.mockReturnValue(response$);

        service.loadTables().subscribe();
        service.loadTables().subscribe();
        expect(apiService.getTables).toHaveBeenCalledTimes(1);

        response$.next(tables);
        response$.complete();

        expect(service.tables().map((t) => t.name)).toEqual(['Customers']);
    });

    it('issues a fresh request once the previous one has completed', () => {
        const tables: PersistenceTable[] = [
            { id: 1, name: 'Customers', description: '', entry_count: 0, created_at: '', updated_at: '' },
        ];
        apiService.getTables.mockReturnValue(of(tables));

        service.loadTables().subscribe();
        service.loadTables().subscribe();

        expect(apiService.getTables).toHaveBeenCalledTimes(2);
    });

    it('drops a late response from a load that started before clear() (org switch)', () => {
        const response$ = new Subject<PersistenceTable[]>();
        apiService.getTables.mockReturnValue(response$);

        service.loadTables().subscribe();
        service.clear();

        response$.next([
            { id: 1, name: 'OrgACustomers', description: '', entry_count: 0, created_at: '', updated_at: '' },
        ]);
        response$.complete();

        expect(service.tables()).toEqual([]);
    });

    it('fires a fresh request after clear() and populates tables from it, not the stale one', () => {
        const staleResponse$ = new Subject<PersistenceTable[]>();
        const freshTables: PersistenceTable[] = [
            { id: 2, name: 'OrgBCustomers', description: '', entry_count: 0, created_at: '', updated_at: '' },
        ];
        apiService.getTables.mockReturnValueOnce(staleResponse$).mockReturnValueOnce(of(freshTables));

        service.loadTables().subscribe();
        service.clear();
        service.loadTables().subscribe();

        expect(apiService.getTables).toHaveBeenCalledTimes(2);
        expect(service.tables().map((t) => t.name)).toEqual(['OrgBCustomers']);
    });

    it('does not let a stale finalize null a newer in-flight load started after clear()', () => {
        const requestA$ = new Subject<PersistenceTable[]>();
        const requestB$ = new Subject<PersistenceTable[]>();
        apiService.getTables.mockReturnValueOnce(requestA$).mockReturnValueOnce(requestB$);

        service.loadTables().subscribe();
        service.clear();
        service.loadTables().subscribe();

        // Stale completion of the pre-clear request must not clear the newer in-flight load.
        requestA$.next([]);
        requestA$.complete();

        service.loadTables().subscribe();

        expect(apiService.getTables).toHaveBeenCalledTimes(2);
    });

    describe('reloadTables (after a create, rename or delete)', () => {
        const before: PersistenceTable[] = [
            { id: 1, name: 'Customers', description: '', entry_count: 0, created_at: '', updated_at: '' },
        ];
        const after: PersistenceTable[] = [
            ...before,
            { id: 2, name: 'Orders', description: '', entry_count: 0, created_at: '', updated_at: '' },
        ];

        it('does not join a pending load, and keeps its own response over the late stale one', () => {
            const staleResponse$ = new Subject<PersistenceTable[]>();
            const freshResponse$ = new Subject<PersistenceTable[]>();
            apiService.getTables.mockReturnValueOnce(staleResponse$).mockReturnValueOnce(freshResponse$);
            const reloaded = vi.fn();

            service.loadTables().subscribe();
            service.reloadTables().subscribe(reloaded);
            expect(apiService.getTables).toHaveBeenCalledTimes(2);

            freshResponse$.next(after);
            freshResponse$.complete();
            expect(reloaded).toHaveBeenCalledWith(after);
            expect(service.tables().map((table) => table.name)).toEqual(['Customers', 'Orders']);

            staleResponse$.next(before);
            staleResponse$.complete();
            expect(service.tables().map((table) => table.name)).toEqual(['Customers', 'Orders']);
        });

        it('stays the load later callers join, even once the superseded load completes', () => {
            const staleResponse$ = new Subject<PersistenceTable[]>();
            const freshResponse$ = new Subject<PersistenceTable[]>();
            apiService.getTables.mockReturnValueOnce(staleResponse$).mockReturnValueOnce(freshResponse$);

            service.loadTables().subscribe();
            service.reloadTables().subscribe();
            // The superseded load's finalize must not drop the reload from inFlightLoad.
            staleResponse$.next(before);
            staleResponse$.complete();
            service.loadTables().subscribe();

            expect(apiService.getTables).toHaveBeenCalledTimes(2);
            freshResponse$.next(after);
            expect(service.tables()).toEqual(after);
        });
    });
});
