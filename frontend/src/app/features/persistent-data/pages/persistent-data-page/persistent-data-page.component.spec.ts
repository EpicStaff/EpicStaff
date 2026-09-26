import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { FilesSearchService } from '../../../files/services/files-search.service';
import { PersistenceEntriesGridComponent } from '../../components/persistence-entries-grid/persistence-entries-grid.component';
import { PersistenceTable } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';
import { PersistentDataPageComponent } from './persistent-data-page.component';

const TABLES: PersistenceTable[] = [
    { id: 1, name: 'profiles', description: '', entry_count: 0, created_at: '', updated_at: '' },
    { id: 2, name: 'orders', description: '', entry_count: 0, created_at: '', updated_at: '' },
];

describe('PersistentDataPageComponent header search', () => {
    it('filters entry keys of the selected table, not the table list, and survives a table switch', () => {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                FilesSearchService,
                { provide: PermissionsService, useValue: { can: () => false } },
                {
                    provide: PersistenceTablesApiService,
                    useValue: {
                        getTables: () => of(TABLES),
                        getEntries: () => of({ count: 0, next: null, previous: null, results: [] }),
                    },
                },
            ],
        });
        const fixture = TestBed.createComponent(PersistentDataPageComponent);
        fixture.detectChanges();
        TestBed.inject(FilesSearchService).setSearchTerm('profile_42');
        fixture.detectChanges();

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelectorAll('.table-list__name')).toHaveLength(2);
        const grid = () =>
            fixture.debugElement.query(By.directive(PersistenceEntriesGridComponent))
                .componentInstance as PersistenceEntriesGridComponent;
        expect(grid().searchTerm()).toBe('profile_42');

        fixture.componentInstance.selectedTableId.set(2);
        fixture.detectChanges();
        expect(grid().table().id).toBe(2);
        expect(grid().searchTerm()).toBe('profile_42');
    });
});
