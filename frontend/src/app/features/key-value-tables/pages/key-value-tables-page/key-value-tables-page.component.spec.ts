import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode } from '@shared/models';
import { NEVER, Observable, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsStorageService } from '../../../../services/recycle-bin';
import { KeyValueEntriesGridComponent } from '../../components/key-value-entries-grid/key-value-entries-grid.component';
import { KeyValueTableDialogComponent } from '../../components/key-value-table-dialog/key-value-table-dialog.component';
import { KeyValueTable, KeyValueTableUsage } from '../../models/key-value-table.model';
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
                { provide: RecycleBinSettingsStorageService, useValue: { retentionDays: signal(7) } },
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
                { provide: RecycleBinSettingsStorageService, useValue: { retentionDays: signal(7) } },
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

describe('KeyValueTablesPageComponent delete table', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function setUpPage(usage: Observable<KeyValueTableUsage>, confirmed = true) {
        const api = {
            getTables: () => of(TABLES),
            getEntries: () => of({ count: 0, next: null, previous: null, results: [] }),
            getUsage: vi.fn(() => usage),
            deleteTable: vi.fn(() => of(undefined)),
        };
        const confirmation = {
            confirm: vi.fn<ConfirmationDialogService['confirm']>(() => of(confirmed)),
            confirmMoveToRecycleBin: vi.fn<ConfirmationDialogService['confirmMoveToRecycleBin']>(() => of(confirmed)),
        };
        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                { provide: PermissionsService, useValue: { can: () => true } },
                { provide: RecycleBinSettingsStorageService, useValue: { retentionDays: signal(7) } },
                { provide: KeyValueTablesApiService, useValue: api },
                { provide: ConfirmationDialogService, useValue: confirmation },
            ],
        });
        const fixture = TestBed.createComponent(KeyValueTablesPageComponent);
        fixture.detectChanges();
        const triggerRefresh = vi.spyOn(TestBed.inject(KeyValueTablesStorageService), 'triggerRefresh');
        const toastSuccess = vi.spyOn(TestBed.inject(ToastService), 'success');
        const message = (): string => confirmation.confirm.mock.calls.at(-1)?.[0].message ?? '';
        const trashButtons = (): HTMLButtonElement[] =>
            Array.from(
                (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>(
                    'app-icon-button[ariaLabel="Delete table"] button'
                )
            );
        return { fixture, api, confirmation, message, trashButtons, triggerRefresh, toastSuccess };
    }

    function renderPage(usage: Observable<KeyValueTableUsage>, confirmed = true) {
        const page = setUpPage(usage, confirmed);
        page.fixture.componentInstance.onDelete(TABLES[0]);
        page.fixture.detectChanges();
        return page;
    }

    it('says one node in one flow uses the table, in the singular, and deletes on confirm', () => {
        const { api, message, triggerRefresh, toastSuccess } = renderPage(of({ node_count: 1, flow_count: 1 }));

        expect(api.getUsage).toHaveBeenCalledWith(1);
        expect(message()).toContain('<strong>profiles</strong>');
        expect(message()).toContain(
            'This table is used by 1 Key-Value node in 1 flow. Deleting it removes the table from that node. ' +
                'That node will need a new table before its flow can run.'
        );
        expect(message()).toContain('It moves to the recycle bin, where you can restore it for 7 days.');
        expect(message()).toContain("Restoring it won't add it back to those nodes.");
        expect(message()).not.toContain('cannot be undone');
        expect(api.deleteTable).toHaveBeenCalledWith(1);
        expect(toastSuccess).toHaveBeenCalledWith('Table "profiles" deleted');
        expect(triggerRefresh).toHaveBeenCalledOnce();
    });

    it('says how many nodes in how many flows use the table, in the plural', () => {
        const { message } = renderPage(of({ node_count: 3, flow_count: 2 }));

        expect(message()).toContain(
            'This table is used by 3 Key-Value nodes in 2 flows. Deleting it removes the table from those nodes. ' +
                'Those nodes will need a new table before their flows can run.'
        );
    });

    it('keeps "flow" singular for several nodes in one flow', () => {
        const { message } = renderPage(of({ node_count: 2, flow_count: 1 }));

        expect(message()).toContain(
            'This table is used by 2 Key-Value nodes in 1 flow. Deleting it removes the table from those nodes. ' +
                'Those nodes will need a new table before their flow can run.'
        );
    });

    it('says an unused table moves to the recycle bin', () => {
        const { api, confirmation } = renderPage(of({ node_count: 0, flow_count: 0 }));

        expect(confirmation.confirmMoveToRecycleBin).toHaveBeenCalledWith('profiles', 7);
        expect(confirmation.confirm).not.toHaveBeenCalled();
        expect(api.deleteTable).toHaveBeenCalledWith(1);
    });

    it('still lets the table be deleted when the usage cannot be fetched, without stating a count', () => {
        const { api, message, triggerRefresh } = renderPage(throwError(() => new HttpErrorResponse({ status: 500 })));

        expect(message()).toContain(
            'If Key-Value nodes use this table, deleting it removes the table from them, and they will need a new ' +
                'table before their flows can run.'
        );
        expect(message()).not.toMatch(/\d+ Key-Value node/);
        expect(api.deleteTable).toHaveBeenCalledWith(1);
        expect(triggerRefresh).toHaveBeenCalledOnce();
    });

    it('does not delete when the confirmation is cancelled', () => {
        const { api, confirmation } = renderPage(of({ node_count: 2, flow_count: 1 }), false);

        expect(confirmation.confirm).toHaveBeenCalledOnce();
        expect(api.deleteTable).not.toHaveBeenCalled();
    });

    it('asks for usage, opens the dialog and deletes once on a double click', () => {
        const usage = new Subject<KeyValueTableUsage>();
        const { fixture, api, confirmation, trashButtons } = setUpPage(usage);
        expect(trashButtons()).toHaveLength(2);

        trashButtons()[0].click();
        // A held Enter repeats the request too.
        fixture.componentInstance.onDelete(TABLES[0]);
        fixture.detectChanges();
        trashButtons()[0].click();
        trashButtons()[1].click();

        expect(api.getUsage).toHaveBeenCalledOnce();

        usage.next({ node_count: 1, flow_count: 1 });
        usage.complete();
        fixture.detectChanges();

        expect(confirmation.confirm).toHaveBeenCalledOnce();
        expect(api.deleteTable).toHaveBeenCalledOnce();
        expect(fixture.componentInstance.deletePending()).toBe(false);
    });

    it('allows another delete once a cancelled one has ended', () => {
        const { fixture, api } = renderPage(of({ node_count: 0, flow_count: 0 }), false);

        fixture.componentInstance.onDelete(TABLES[1]);

        expect(api.getUsage).toHaveBeenCalledTimes(2);
        expect(api.getUsage).toHaveBeenLastCalledWith(2);
    });
});
