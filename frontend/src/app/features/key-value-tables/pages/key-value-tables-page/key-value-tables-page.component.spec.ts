import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { ActionCode } from '@shared/models';
import { NEVER, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { KeyValueEntriesGridComponent } from '../../components/key-value-entries-grid/key-value-entries-grid.component';
import { KeyValueTableDialogComponent } from '../../components/key-value-table-dialog/key-value-table-dialog.component';
import { KeyValueTable } from '../../models/key-value-table.model';
import { KeyValueTablesApiService } from '../../services/key-value-tables-api.service';
import { KeyValueTablesStorageService } from '../../services/key-value-tables-storage.service';
import { KeyValueTablesPageComponent } from './key-value-tables-page.component';

const TABLES: KeyValueTable[] = [
    { id: 1, name: 'profiles', description: '', entry_count: 0, created_at: '', updated_at: '' },
    { id: 2, name: 'orders', description: '', entry_count: 0, created_at: '', updated_at: '' },
];

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('KeyValueTablesPageComponent key search', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('filters entry keys of the selected table, not the table list, and survives a table switch', () => {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                { provide: PermissionsService, useValue: { can: () => false } },
                {
                    provide: KeyValueTablesApiService,
                    useValue: {
                        getTables: () => of(TABLES),
                        getEntries: () => of({ count: 0, next: null, previous: null, results: [] }),
                    },
                },
            ],
        });
        const fixture = TestBed.createComponent(KeyValueTablesPageComponent);
        fixture.detectChanges();
        const grid = () =>
            fixture.debugElement.query(By.directive(KeyValueEntriesGridComponent))
                .componentInstance as KeyValueEntriesGridComponent;
        grid().searchTerm.set('profile_42');
        fixture.detectChanges();

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelectorAll('.table-list__name')).toHaveLength(2);

        fixture.componentInstance.selectedTableId.set(2);
        fixture.detectChanges();
        expect(grid().table().id).toBe(2);
        expect(grid().searchTerm()).toBe('profile_42');
    });
});

describe('KeyValueTablesPageComponent create table', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function renderPage(canCreate: boolean, created: KeyValueTable | null = null) {
        const dialogOpen = vi.fn(() => ({ closed: created ? of(created) : NEVER }));
        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                // Only the create verb is granted, so the Add button is the one thing under test.
                {
                    provide: PermissionsService,
                    useValue: { can: (_: string, action: ActionCode) => canCreate && action === ActionCode.Create },
                },
                { provide: Dialog, useValue: { open: dialogOpen } },
                {
                    provide: KeyValueTablesApiService,
                    useValue: {
                        getTables: () => of(TABLES),
                        getEntries: () => of({ count: 0, next: null, previous: null, results: [] }),
                    },
                },
            ],
        });
        const fixture = TestBed.createComponent(KeyValueTablesPageComponent);
        fixture.detectChanges();
        const addButton = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>(
            '.table-list__header app-button'
        );
        return { fixture, addButton, dialogOpen };
    }

    it('opens the create-table dialog from the sidebar header Add button', () => {
        const { addButton, dialogOpen } = renderPage(true);
        addButton?.click();
        expect(dialogOpen).toHaveBeenCalledWith(KeyValueTableDialogComponent, { width: '480px' });
    });

    it('selects the created table, toasts and reloads the list', () => {
        const { fixture, addButton } = renderPage(true, TABLES[1]);
        const toastSuccess = vi.spyOn(TestBed.inject(ToastService), 'success');
        const triggerRefresh = vi.spyOn(TestBed.inject(KeyValueTablesStorageService), 'triggerRefresh');
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
