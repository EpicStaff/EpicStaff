import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { PersistenceTable } from '../../models/persistence-table.model';
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
