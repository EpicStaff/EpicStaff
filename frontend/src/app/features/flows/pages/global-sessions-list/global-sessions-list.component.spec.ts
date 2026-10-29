import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { GraphSessionStatus } from '@shared/models';
import { firstValueFrom, throwError } from 'rxjs';

import { forbiddenInterceptor } from '../../../../core/interceptors/forbidden.interceptor';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { ToastMessage, ToastService } from '../../../../services/notifications';
import { GraphSessionLight } from '../../services/flows-sessions.service';
import { GlobalSessionsListComponent } from './global-sessions-list.component';

function session(id: number): GraphSessionLight {
    return {
        id,
        graph_id: 7,
        graph_name: 'Orders',
        status: GraphSessionStatus.ENDED,
        status_updated_at: '2026-10-01T10:00:00Z',
        created_at: '2026-10-01T10:00:00Z',
        finished_at: '2026-10-01T10:01:00Z',
        trigger: null,
    };
}

function sessions(fromId: number, toId: number): GraphSessionLight[] {
    return Array.from({ length: toId - fromId + 1 }, (_, index) => session(fromId + index));
}

// jsdom has no ResizeObserver; the confirmation dialog's buttons only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('GlobalSessionsListComponent deleting sessions', () => {
    let fixture: ComponentFixture<GlobalSessionsListComponent>;
    let http: HttpTestingController;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            providers: [
                // the real forbidden interceptor, so a 403 is toasted exactly as in the app
                provideHttpClient(withInterceptors([forbiddenInterceptor])),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                {
                    provide: PermissionsService,
                    useValue: { can: () => true, canAny: () => true } as unknown as PermissionsService,
                },
                {
                    // the permission refresh after a 403 fails, so the interceptor does not navigate
                    provide: ProfileService,
                    useValue: {
                        clearCurrentUser: () => undefined,
                        bootstrapUser: () => throwError(() => new Error('offline')),
                    } as unknown as ProfileService,
                },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(GlobalSessionsListComponent);
        fixture.detectChanges();
        http.expectOne((request) => request.url === '/api/graph-light/').flush({ count: 0, next: null, results: [] });
    });

    afterEach(() => {
        // destroy first: it stops the background refresh before verify() checks for open requests
        fixture.destroy();
        vi.unstubAllGlobals();
        http.verify();
    });

    /** Answers the pending page request and returns the offset it asked for. */
    function respondWithSessions(page: GraphSessionLight[], totalCount = page.length): string | null {
        fixture.detectChanges();
        const request = http.expectOne((pending) => pending.method === 'GET' && pending.url === '/api/sessions/');
        request.flush({ count: totalCount, results: page });
        fixture.detectChanges();
        return request.request.params.get('offset');
    }

    function host(): HTMLElement {
        return fixture.nativeElement as HTMLElement;
    }

    function tickSession(id: number): void {
        host().querySelector<HTMLInputElement>(`#session-checkbox-${id} input`)!.click();
        fixture.detectChanges();
    }

    function deleteButton(): HTMLButtonElement {
        return host().querySelector<HTMLButtonElement>('.delete-btn')!;
    }

    function clickDeleteSelected(): void {
        deleteButton().click();
        fixture.detectChanges();
    }

    function clickRowDelete(id: number): void {
        const row = host().querySelector(`#session-checkbox-${id}`)!.closest('tr')!;
        row.querySelector<HTMLButtonElement>('button[aria-label="Delete session"]')!.click();
        fixture.detectChanges();
    }

    function confirmationDialog(): HTMLElement | null {
        return document.querySelector<HTMLElement>('.dialog-container');
    }

    function dialogText(selector: '.dialog-title' | '.dialog-message'): string {
        return confirmationDialog()!.querySelector(selector)!.textContent!.trim();
    }

    function clickDialogButton(selector: '.confirm-button' | '.cancel-button'): void {
        confirmationDialog()!.querySelector<HTMLButtonElement>(selector)!.click();
        fixture.detectChanges();
    }

    function expectBulkDelete(): TestRequest {
        return http.expectOne((request) => request.method === 'POST' && request.url === '/api/sessions/bulk_delete/');
    }

    function expectNoBulkDelete(): void {
        http.expectNone((request) => request.url === '/api/sessions/bulk_delete/');
    }

    function shownToasts(): Promise<Pick<ToastMessage, 'type' | 'message'>[]> {
        return firstValueFrom(TestBed.inject(ToastService).toasts$).then((toasts) =>
            toasts.map(({ type, message }) => ({ type, message }))
        );
    }

    function deleteSelectedAndConfirm(...ids: number[]): TestRequest {
        ids.forEach((id) => tickSession(id));
        clickDeleteSelected();
        clickDialogButton('.confirm-button');
        return expectBulkDelete();
    }

    describe('on a page of three sessions', () => {
        beforeEach(() => respondWithSessions(sessions(1, 3)));

        it('asks for confirmation before deleting, and the dialog names the selected count', () => {
            tickSession(1);
            tickSession(2);
            tickSession(3);

            clickDeleteSelected();

            expect(dialogText('.dialog-title')).toBe('Delete 3 sessions?');
            expect(dialogText('.dialog-message')).toBe("3 sessions will be permanently deleted. This can't be undone.");
            expectNoBulkDelete();
        });

        it('names the session when only one is selected', () => {
            tickSession(2);

            clickDeleteSelected();

            expect(dialogText('.dialog-title')).toBe('Delete session #2?');
            expect(dialogText('.dialog-message')).toBe("Session #2 will be permanently deleted. This can't be undone.");
        });

        it('deletes after confirming, toasts the deleted count and clears the selection', async () => {
            const request = deleteSelectedAndConfirm(1, 3);

            expect(request.request.body).toEqual({ ids: [1, 3] });
            request.flush({ deleted: 2, ids: [1, 3] });
            respondWithSessions([session(2)]);

            expect(await shownToasts()).toEqual([{ type: 'success', message: 'Deleted 2 sessions.' }]);
            expect(deleteButton().textContent!.trim()).toBe('Delete Selected (0)');
        });

        it('says the sessions were already deleted when the server deleted none of them', async () => {
            deleteSelectedAndConfirm(1).flush({ deleted: 0, ids: [1] });
            respondWithSessions(sessions(2, 3));

            expect(await shownToasts()).toEqual([{ type: 'success', message: 'Already deleted.' }]);
        });

        it('sends nothing when the user cancels', async () => {
            tickSession(2);
            clickDeleteSelected();

            clickDialogButton('.cancel-button');

            expectNoBulkDelete();
            expect(confirmationDialog()).toBeNull();
            expect(deleteButton().textContent!.trim()).toBe('Delete Selected (1)');
            expect(await shownToasts()).toEqual([]);
        });

        it('shows an error toast and keeps the selection when the delete fails', async () => {
            deleteSelectedAndConfirm(2).flush(
                { detail: 'Database is unavailable.' },
                { status: 500, statusText: 'Server Error' }
            );
            fixture.detectChanges();

            expect(await shownToasts()).toEqual([{ type: 'error', message: 'Database is unavailable.' }]);
            expect(deleteButton().textContent!.trim()).toBe('Delete Selected (1)');
        });

        it('shows a plain 403 once: the forbidden interceptor toasts it, the delete adds nothing', async () => {
            deleteSelectedAndConfirm(2).flush(
                { message: 'You do not have permission to delete sessions.' },
                { status: 403, statusText: 'Forbidden' }
            );
            fixture.detectChanges();

            expect(await shownToasts()).toEqual([
                { type: 'error', message: 'You do not have permission to delete sessions.' },
            ]);
        });

        it('toasts a 403 the forbidden interceptor leaves to the caller', async () => {
            deleteSelectedAndConfirm(2).flush(
                { code: 'in_use_restricted', message: 'Session is in use.' },
                { status: 403, statusText: 'Forbidden' }
            );
            fixture.detectChanges();

            expect(await shownToasts()).toEqual([{ type: 'error', message: 'Session is in use.' }]);
        });

        it('cannot start a second delete while the first request is in flight', () => {
            const request = deleteSelectedAndConfirm(1);

            expect(deleteButton().disabled).toBe(true);
            clickDeleteSelected();
            clickRowDelete(3);

            expect(confirmationDialog()).toBeNull();
            request.flush({ deleted: 1, ids: [1] });
            respondWithSessions(sessions(2, 3));
            expect(deleteButton().disabled).toBe(false);
        });

        it('does not disable the button while the user is still deciding', () => {
            tickSession(1);
            clickDeleteSelected();

            expect(deleteButton().disabled).toBe(false);
            clickDialogButton('.cancel-button');
        });

        it('asks for confirmation before deleting a single session from its row', async () => {
            clickRowDelete(3);

            expect(dialogText('.dialog-title')).toBe('Delete session #3?');
            expectNoBulkDelete();

            clickDialogButton('.confirm-button');
            expectBulkDelete().flush({ deleted: 1, ids: [3] });
            respondWithSessions(sessions(1, 2));

            expect(await shownToasts()).toEqual([{ type: 'success', message: 'Deleted 1 session.' }]);
        });
    });

    it('goes back a page after deleting the only session on the last page', () => {
        // page 1 of 11 sessions shows 10; go to page 2, which holds only session 11
        expect(respondWithSessions(sessions(1, 10), 11)).toBe('0');
        host()
            .querySelectorAll<HTMLButtonElement>('.page-btn')
            .forEach((button) => button.textContent!.trim() === '2' && button.click());
        expect(respondWithSessions([session(11)], 11)).toBe('10');

        clickRowDelete(11);
        clickDialogButton('.confirm-button');
        expectBulkDelete().flush({ deleted: 1, ids: [11] });

        expect(respondWithSessions(sessions(1, 10), 10)).toBe('0');
    });
});
