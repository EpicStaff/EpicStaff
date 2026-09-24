import { TestBed } from '@angular/core/testing';
import { NEVER, of } from 'rxjs';

import { PersistenceTable, PersistenceTableEntry } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';
import { PersistenceEntriesGridComponent } from './persistence-entries-grid.component';

const TABLE: PersistenceTable = {
    id: 1,
    name: 'profiles',
    description: '',
    entry_count: 0,
    created_at: '2026-09-24T00:00:00Z',
    updated_at: '2026-09-24T00:00:00Z',
};

function actionIcons(canUpdate: boolean, canDelete: boolean): string[] | undefined {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PersistenceTablesApiService,
                useValue: { getEntries: () => of({ count: 0, next: null, previous: null, results: [] }) },
            },
        ],
    });
    const fixture = TestBed.createComponent(PersistenceEntriesGridComponent);
    fixture.componentRef.setInput('table', TABLE);
    fixture.componentRef.setInput('canUpdate', canUpdate);
    fixture.componentRef.setInput('canDelete', canDelete);
    const actionsColumn = fixture.componentInstance.columns().find((column) => column.key === 'actions');
    return actionsColumn?.actions?.map((action) => action.icon);
}

describe('PersistenceEntriesGridComponent table switch', () => {
    it("drops the previous table's rows while the new table loads", () => {
        const entry: PersistenceTableEntry = {
            id: 7,
            table: 1,
            key: 'k',
            value: 'v',
            created_at: '2026-09-24T00:00:00Z',
            updated_at: '2026-09-24T00:00:00Z',
            updated_by_session: null,
            updated_by_graph: null,
        };
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: PersistenceTablesApiService,
                    // Table 2's load never answers, like a slow or failed request.
                    useValue: {
                        getEntries: (params: { table: number }) =>
                            params.table === 1 ? of({ count: 1, next: null, previous: null, results: [entry] }) : NEVER,
                    },
                },
            ],
        });
        const fixture = TestBed.createComponent(PersistenceEntriesGridComponent);
        fixture.componentRef.setInput('table', TABLE);
        fixture.detectChanges();
        expect(fixture.componentInstance.entries()).toEqual([entry]);

        fixture.componentRef.setInput('table', { ...TABLE, id: 2, name: 'orders' });
        fixture.detectChanges();

        expect(fixture.componentInstance.entries()).toEqual([]);
        expect(fixture.componentInstance.totalCount()).toBe(0);
    });
});

describe('PersistenceEntriesGridComponent permission gating', () => {
    it('offers only edit with update permission only', () => {
        expect(actionIcons(true, false)).toEqual(['edit']);
    });

    it('offers only delete with delete permission only', () => {
        expect(actionIcons(false, true)).toEqual(['trash']);
    });

    it('omits the actions column without update or delete permission', () => {
        expect(actionIcons(false, false)).toBeUndefined();
    });
});
