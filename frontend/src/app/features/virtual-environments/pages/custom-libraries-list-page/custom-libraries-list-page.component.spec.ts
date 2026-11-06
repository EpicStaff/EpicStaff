import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, Subject } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { CustomLibrary, WheelStatus } from '../../models/custom-library.model';
import { CustomLibrariesListPageComponent } from './custom-libraries-list-page.component';

const API_URL = 'http://api/';
const POLL_INTERVAL_MS = 2_000;

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function library(id: number, name: string | null, status: WheelStatus | null = 'completed'): CustomLibrary {
    return {
        id,
        name,
        owner: { id: 1, email: 'dana@example.com', display_name: 'Dana' },
        status,
        error: status === 'failed' ? 'no setup.py' : null,
        created_at: '2026-01-02T03:04:05Z',
        updated_at: '2026-01-02T03:04:05Z',
    };
}

describe('CustomLibrariesListPageComponent', () => {
    let fixture: ComponentFixture<CustomLibrariesListPageComponent>;
    let host: HTMLElement;
    let http: HttpTestingController;
    let confirmation: Subject<boolean>;
    let dialogClosed: Subject<unknown>;

    function answerList(libraries: CustomLibrary[]): void {
        const pending = http.match((request) => request.url === `${API_URL}custom-libraries/`);
        expect(pending).toHaveLength(1);
        pending[0].flush({
            count: libraries.length,
            limit: 1000,
            offset: 0,
            next: null,
            previous: null,
            result: libraries,
        });
        fixture.detectChanges();
    }

    function renderedNames(): string[] {
        return Array.from(host.querySelectorAll('.custom-library-card__name')).map((node) => node.textContent!.trim());
    }

    function deleteButton(index = 0): HTMLElement {
        return host.querySelectorAll<HTMLElement>('.custom-library-card__icon-btn').item(index);
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        confirmation = new Subject<boolean>();
        dialogClosed = new Subject<unknown>();

        TestBed.configureTestingModule({
            imports: [CustomLibrariesListPageComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
                {
                    provide: ConfirmationDialogService,
                    useValue: { confirmDelete: (): Observable<boolean> => confirmation },
                },
                { provide: Dialog, useValue: { open: () => ({ closed: dialogClosed }) } },
            ],
        });

        fixture = TestBed.createComponent(CustomLibrariesListPageComponent);
        host = fixture.nativeElement as HTMLElement;
        http = TestBed.inject(HttpTestingController);
        fixture.detectChanges();
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('shows a row per library the backend answers with', () => {
        answerList([library(1, 'acme-utils'), library(2, 'acme-ml')]);

        expect(renderedNames()).toEqual(['acme-utils', 'acme-ml']);
        expect(host.querySelector('.custom-library-card__meta')!.textContent).toContain('Dana');
    });

    it('marks a library whose version did not build, and leaves a built one unmarked', () => {
        answerList([library(1, 'acme-utils', 'failed'), library(2, 'acme-ml')]);

        const badges = host.querySelectorAll('.venv-status');
        expect(badges).toHaveLength(1);
        expect(badges[0].textContent).toContain('Failed');
    });

    it('follows a library that is still building until nothing is building', () => {
        answerList([library(1, 'acme-utils', 'processing')]);
        expect(host.querySelector('.venv-status')!.textContent).toContain('Building');

        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        answerList([library(1, 'acme-utils', 'completed')]);

        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        expect(http.match(() => true)).toHaveLength(0);
    });

    it('offers to create the first library when there is none', () => {
        answerList([]);

        expect(host.querySelector('.custom-libraries__empty')!.textContent).toContain('No custom libraries yet');
    });

    it('deletes only after the confirmation is answered, then reloads the list', () => {
        answerList([library(1, 'acme-utils')]);

        deleteButton().click();
        fixture.detectChanges();
        expect(http.match(() => true)).toHaveLength(0);

        confirmation.next(true);
        confirmation.complete();
        fixture.detectChanges();
        http.expectOne({ method: 'DELETE', url: `${API_URL}custom-libraries/1/` }).flush(null, {
            status: 204,
            statusText: 'No Content',
        });
        fixture.detectChanges();

        answerList([]);
        expect(renderedNames()).toEqual([]);
    });

    it('ignores a second delete while the first is still waiting on its confirmation', () => {
        answerList([library(1, 'acme-utils'), library(2, 'acme-ml')]);

        deleteButton(0).click();
        deleteButton(1).click();
        fixture.detectChanges();

        confirmation.next(true);
        confirmation.complete();
        fixture.detectChanges();

        const deletes = http.match((request) => request.method === 'DELETE');
        expect(deletes).toHaveLength(1);
        expect(deletes[0].request.url).toBe(`${API_URL}custom-libraries/1/`);
        deletes[0].flush(null, { status: 204, statusText: 'No Content' });
        answerList([library(2, 'acme-ml')]);
    });

    it('shows only the libraries whose name holds the search term', () => {
        answerList([library(1, 'acme-utils'), library(2, 'print-hello-world'), library(3, null)]);

        fixture.componentRef.setInput('searchTerm', 'HELLO');
        fixture.detectChanges();

        // Case is not part of a name, and a library no build has named yet matches nothing.
        expect(renderedNames()).toEqual(['print-hello-world']);
    });

    it('says the search matched nothing rather than offering to create the first library', () => {
        answerList([library(1, 'acme-utils')]);

        fixture.componentRef.setInput('searchTerm', 'zeta');
        fixture.detectChanges();

        expect(host.querySelector('.custom-libraries__empty')!.textContent).toContain('match "zeta"');
    });

    it.each([
        ['name_asc', ['acme-utils', 'print-hello-world', 'Naming pending…']],
        ['name_desc', ['print-hello-world', 'acme-utils', 'Naming pending…']],
    ])('orders the list by %s', (order, expected) => {
        answerList([library(2, 'print-hello-world'), library(3, null), library(1, 'acme-utils')]);

        fixture.componentRef.setInput('sortOrder', order);
        fixture.detectChanges();

        // A library with no name sorts last either way: there is nothing to order it by.
        expect(renderedNames()).toEqual(expected);
    });

    it('leaves the backend order alone by default', () => {
        answerList([library(2, 'print-hello-world'), library(1, 'acme-utils')]);

        expect(renderedNames()).toEqual(['print-hello-world', 'acme-utils']);
    });

    it('reloads the list when the dialog reports a change', () => {
        answerList([library(1, 'acme-utils')]);

        host.querySelector<HTMLElement>('.custom-library-card')!.click();
        fixture.detectChanges();
        dialogClosed.next('changed');
        fixture.detectChanges();

        answerList([library(1, 'acme-utils')]);
        expect(renderedNames()).toEqual(['acme-utils']);
    });

    it('leaves the list alone when the dialog changed nothing', () => {
        answerList([library(1, 'acme-utils')]);

        host.querySelector<HTMLElement>('.custom-library-card')!.click();
        fixture.detectChanges();
        dialogClosed.next(null);
        fixture.detectChanges();

        expect(http.match(() => true)).toHaveLength(0);
    });
});
