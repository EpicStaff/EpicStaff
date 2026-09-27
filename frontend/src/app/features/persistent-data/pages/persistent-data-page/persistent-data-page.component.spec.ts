import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { ActionCode } from '@shared/models';
import { NEVER, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { FilesSearchService } from '../../../files/services/files-search.service';
import { PersistenceEntriesGridComponent } from '../../components/persistence-entries-grid/persistence-entries-grid.component';
import { PersistenceTableDialogComponent } from '../../components/persistence-table-dialog/persistence-table-dialog.component';
import { PersistenceTable } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';
import { PersistenceTablesStorageService } from '../../services/persistence-tables-storage.service';
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

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('PersistentDataPageComponent create table', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function renderPage(canCreate: boolean, created: PersistenceTable | null = null) {
        const dialogOpen = vi.fn(() => ({ closed: created ? of(created) : NEVER }));
        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                FilesSearchService,
                // Only the create verb is granted, so the Add button is the one thing under test.
                {
                    provide: PermissionsService,
                    useValue: { can: (_: string, action: ActionCode) => canCreate && action === ActionCode.Create },
                },
                { provide: Dialog, useValue: { open: dialogOpen } },
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
        const addButton = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>(
            '.table-list__header app-button'
        );
        return { fixture, addButton, dialogOpen };
    }

    it('opens the create-table dialog from the sidebar header Add button', () => {
        const { addButton, dialogOpen } = renderPage(true);
        addButton?.click();
        expect(dialogOpen).toHaveBeenCalledWith(PersistenceTableDialogComponent, { width: '480px' });
    });

    it('selects the created table, toasts and reloads the list', () => {
        const { fixture, addButton } = renderPage(true, TABLES[1]);
        const toastSuccess = vi.spyOn(TestBed.inject(ToastService), 'success');
        const triggerRefresh = vi.spyOn(TestBed.inject(PersistenceTablesStorageService), 'triggerRefresh');
        expect(fixture.componentInstance.selectedTableId()).toBe(1);

        addButton?.click();
        fixture.detectChanges();

        expect(toastSuccess).toHaveBeenCalledWith('Table "orders" created');
        expect(triggerRefresh).toHaveBeenCalledOnce();
        expect(fixture.componentInstance.selectedTableId()).toBe(2);
    });

    it('hides the Add button without create permission', () => {
        expect(renderPage(false).addButton).toBeNull();
    });
});
