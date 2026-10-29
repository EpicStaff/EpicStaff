import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { GraphSessionStatus } from '@shared/models';
import { firstValueFrom } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastMessage, ToastService } from '../../../../services/notifications';
import { GraphDto } from '../../models/graph.model';
import { GraphSessionLight } from '../../services/flows-sessions.service';
import { FlowSessionsListComponent } from './flow-sessions-list.component';

const FLOW_ID = 7;

function session(id: number): GraphSessionLight {
    return {
        id,
        graph_id: FLOW_ID,
        graph_name: 'Orders',
        // finished, so the list does not start polling for status updates
        status: GraphSessionStatus.ENDED,
        status_updated_at: '2026-10-01T10:00:00Z',
        created_at: '2026-10-01T10:00:00Z',
        finished_at: '2026-10-01T10:01:00Z',
        trigger: null,
    };
}

// jsdom has no ResizeObserver; the confirmation dialog's buttons only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('FlowSessionsListComponent "Delete Selected"', () => {
    let fixture: ComponentFixture<FlowSessionsListComponent>;
    let http: HttpTestingController;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                {
                    provide: PermissionsService,
                    useValue: { can: () => true, canAny: () => true } as unknown as PermissionsService,
                },
                { provide: DIALOG_DATA, useValue: { flow: { id: FLOW_ID, name: 'Orders' } as GraphDto } },
                { provide: DialogRef, useValue: { close: () => undefined } },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(FlowSessionsListComponent);
        fixture.detectChanges();
        respondWithSessions([session(1), session(2), session(3)]);
    });

    afterEach(() => {
        fixture.destroy();
        vi.unstubAllGlobals();
        http.verify();
    });

    function respondWithSessions(sessions: GraphSessionLight[]): void {
        fixture.detectChanges();
        http.expectOne((request) => request.method === 'GET' && request.url === '/api/sessions/').flush({
            count: sessions.length,
            results: sessions,
        });
        fixture.detectChanges();
    }

    function tickSession(id: number): void {
        const checkbox = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
            `#session-checkbox-${id} input`
        );
        checkbox!.click();
        fixture.detectChanges();
    }

    function clickDeleteSelected(): void {
        (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.delete-btn')!.click();
        fixture.detectChanges();
    }

    function clickRowDelete(id: number): void {
        const row = (fixture.nativeElement as HTMLElement).querySelector(`#session-checkbox-${id}`)!.closest('tr')!;
        row.querySelector<HTMLButtonElement>('button[aria-label="Delete session"]')!.click();
        fixture.detectChanges();
    }

    function confirmationDialog(): HTMLElement | null {
        return document.querySelector<HTMLElement>('.dialog-container');
    }

    function clickDialogButton(selector: '.confirm-button' | '.cancel-button'): void {
        confirmationDialog()!.querySelector<HTMLButtonElement>(selector)!.click();
        fixture.detectChanges();
    }

    function expectBulkDelete(): TestRequest {
        return http.expectOne((request) => request.method === 'POST' && request.url === '/api/sessions/bulk_delete/');
    }

    function shownToasts(): Promise<Pick<ToastMessage, 'type' | 'message'>[]> {
        return firstValueFrom(TestBed.inject(ToastService).toasts$).then((toasts) =>
            toasts.map(({ type, message }) => ({ type, message }))
        );
    }

    function tickedSessionIds(): number[] {
        return Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLInputElement>('td.col-select input:checked')
        ).map((checkbox) => Number(checkbox.closest('app-checkbox')!.id.replace('session-checkbox-', '')));
    }

    it('asks for confirmation, stating how many sessions will be permanently deleted', () => {
        tickSession(1);
        tickSession(3);

        clickDeleteSelected();

        expect(confirmationDialog()!.querySelector('.dialog-title')!.textContent!.trim()).toBe('Delete 2 sessions?');
        expect(confirmationDialog()!.querySelector('.dialog-message')!.textContent!.trim()).toBe(
            "2 sessions will be permanently deleted. This can't be undone."
        );
        http.expectNone((request) => request.url === '/api/sessions/bulk_delete/');
    });

    it('deletes after confirming, toasts the count the server deleted, clears the selection and reloads', async () => {
        tickSession(1);
        tickSession(3);
        clickDeleteSelected();

        clickDialogButton('.confirm-button');

        const request = expectBulkDelete();
        expect(request.request.body).toEqual({ ids: [1, 3] });
        // one of the two was already deleted elsewhere: the toast reports what this request removed
        request.flush({ deleted: 1, ids: [1, 3] });
        respondWithSessions([session(2)]);

        expect(await shownToasts()).toEqual([{ type: 'success', message: 'Deleted 1 session.' }]);
        expect(tickedSessionIds()).toEqual([]);
        expect(
            Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('td.col-id')).map((cell) =>
                cell.textContent!.trim()
            )
        ).toEqual(['2']);
    });

    it('sends nothing and keeps the selection when the user cancels', async () => {
        tickSession(2);
        clickDeleteSelected();

        clickDialogButton('.cancel-button');

        http.expectNone((request) => request.url === '/api/sessions/bulk_delete/');
        expect(confirmationDialog()).toBeNull();
        expect(tickedSessionIds()).toEqual([2]);
        expect(await shownToasts()).toEqual([]);
    });

    it('shows an error toast and keeps the selection when the delete fails', async () => {
        tickSession(2);
        clickDeleteSelected();
        clickDialogButton('.confirm-button');

        expectBulkDelete().flush({ detail: 'Database is unavailable.' }, { status: 500, statusText: 'Server Error' });
        fixture.detectChanges();

        expect(await shownToasts()).toEqual([{ type: 'error', message: 'Database is unavailable.' }]);
        expect(tickedSessionIds()).toEqual([2]);
    });

    it('asks for confirmation before deleting a single session from its row', async () => {
        clickRowDelete(3);

        expect(confirmationDialog()!.querySelector('.dialog-title')!.textContent!.trim()).toBe('Delete session #3?');
        http.expectNone((request) => request.url === '/api/sessions/bulk_delete/');

        clickDialogButton('.confirm-button');
        expectBulkDelete().flush({ deleted: 1, ids: [3] });
        respondWithSessions([session(1), session(2)]);

        expect(await shownToasts()).toEqual([{ type: 'success', message: 'Deleted 1 session.' }]);
    });

    it('cannot start a second delete while the first request is in flight', () => {
        tickSession(1);
        clickDeleteSelected();
        clickDialogButton('.confirm-button');
        const request = expectBulkDelete();
        const deleteButton = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.delete-btn')!;

        expect(deleteButton.disabled).toBe(true);
        clickDeleteSelected();
        clickRowDelete(3);

        expect(confirmationDialog()).toBeNull();
        request.flush({ deleted: 1, ids: [1] });
        respondWithSessions([session(2), session(3)]);
        expect(deleteButton.disabled).toBe(false);
    });
});
