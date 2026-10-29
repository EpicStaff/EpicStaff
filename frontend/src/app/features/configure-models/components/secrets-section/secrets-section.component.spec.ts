import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Secret } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
import { SecretsSectionComponent } from './secrets-section.component';

const API_URL = 'http://api/';
const SECRETS_URL = `${API_URL}secrets/`;

function secret(id: number, name: string): Secret {
    return {
        id,
        name,
        tail: 'abcd',
        metadata: null,
        org: 1,
        created_at: '2026-10-01T10:00:00Z',
        updated_at: '2026-10-01T10:00:00Z',
        usage_count: { readable: 0, hidden: 0 },
        created_by: null,
    };
}

const OPENAI = secret(1, 'OpenAI key');
const ANTHROPIC = secret(2, 'Anthropic key');
const SLACK = secret(3, 'Slack token');

interface ShownToast {
    type: 'success' | 'error' | 'warning' | 'info';
    message: string;
}

class ToastRecorder {
    readonly shown: ShownToast[] = [];
    success(message: string): void {
        this.shown.push({ type: 'success', message });
    }
    error(message: string): void {
        this.shown.push({ type: 'error', message });
    }
    warning(message: string): void {
        this.shown.push({ type: 'warning', message });
    }
    info(message: string): void {
        this.shown.push({ type: 'info', message });
    }
}

// jsdom has no ResizeObserver; the overflow directive behind the header's <app-button> only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

function render(): {
    fixture: ComponentFixture<SecretsSectionComponent>;
    http: HttpTestingController;
    toasts: ToastRecorder;
} {
    const toasts = new ToastRecorder();
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: API_URL } },
            { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
            { provide: ConfirmationDialogService, useValue: { confirm: () => of(true) } },
            { provide: RecycleBinSettingsService, useValue: { retentionDays: signal(7) } },
            { provide: ToastService, useValue: toasts },
        ],
    });
    const fixture = TestBed.createComponent(SecretsSectionComponent);
    const http = TestBed.inject(HttpTestingController);
    return { fixture, http, toasts };
}

/** Answers the list load: the live secrets, and an unreadable recycle bin (it only names binned ones in pickers). */
function answerListLoad(http: HttpTestingController, secrets: Secret[]): void {
    http.expectOne(SECRETS_URL).flush({ results: secrets });
    http.expectOne((request) => request.url === `${SECRETS_URL}recycle-bin/`).flush(null, {
        status: 500,
        statusText: 'Server Error',
    });
}

function host(fixture: ComponentFixture<SecretsSectionComponent>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

function selectAllRows(fixture: ComponentFixture<SecretsSectionComponent>): void {
    host(fixture)
        .querySelectorAll<HTMLElement>('.table-row')
        .forEach((row) => row.click());
    fixture.detectChanges();
}

function bulkDeleteButton(fixture: ComponentFixture<SecretsSectionComponent>): HTMLButtonElement | null {
    return host(fixture).querySelector<HTMLButtonElement>('button[aria-label^="Delete selected"]');
}

function shownNames(fixture: ComponentFixture<SecretsSectionComponent>): string[] {
    return Array.from(host(fixture).querySelectorAll('.secrets-section__name'), (name) => name.textContent!.trim());
}

describe('SecretsSectionComponent bulk delete', () => {
    it('deletes the rest when one secret was already deleted elsewhere, then shows the fresh list with nothing ticked', () => {
        const { fixture, http, toasts } = render();
        fixture.detectChanges();
        answerListLoad(http, [OPENAI, ANTHROPIC, SLACK]);
        fixture.detectChanges();
        selectAllRows(fixture);
        expect(bulkDeleteButton(fixture)?.getAttribute('aria-label')).toBe('Delete selected (3)');

        bulkDeleteButton(fixture)!.click();
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}1/` }).flush(null);
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}2/` }).flush(
            { message: 'No Secret matches the given query.' },
            { status: 404, statusText: 'Not Found' }
        );
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}3/` }).flush(null);

        expect(toasts.shown).toEqual([
            {
                type: 'success',
                message: 'Moved 2 secrets to the recycle bin. 1 was already deleted: Anthropic key.',
            },
        ]);

        fixture.detectChanges();
        answerListLoad(http, []);
        fixture.detectChanges();
        expect(shownNames(fixture)).toEqual([]);
        expect(bulkDeleteButton(fixture)).toBeNull();
        http.verify();
    });

    it('shows an error naming the secrets that failed for another reason, and keeps them in the list unticked', () => {
        const { fixture, http, toasts } = render();
        fixture.detectChanges();
        answerListLoad(http, [OPENAI, ANTHROPIC]);
        fixture.detectChanges();
        selectAllRows(fixture);

        bulkDeleteButton(fixture)!.click();
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}1/` }).flush(null);
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}2/` }).flush(
            { message: 'The database is unavailable.' },
            { status: 500, statusText: 'Server Error' }
        );

        expect(toasts.shown).toEqual([
            { type: 'success', message: 'Moved 1 secret to the recycle bin.' },
            {
                type: 'error',
                message: "Couldn't delete 1 secret. The database is unavailable. Not deleted: Anthropic key.",
            },
        ]);

        fixture.detectChanges();
        answerListLoad(http, [ANTHROPIC]);
        fixture.detectChanges();
        expect(shownNames(fixture)).toEqual(['Anthropic key']);
        expect(host(fixture).querySelectorAll('.table-row.selected')).toHaveLength(0);
        expect(bulkDeleteButton(fixture)).toBeNull();
        http.verify();
    });

    it('only notes the already-deleted ones when every selected secret was gone', () => {
        const { fixture, http, toasts } = render();
        fixture.detectChanges();
        answerListLoad(http, [OPENAI, ANTHROPIC]);
        fixture.detectChanges();
        selectAllRows(fixture);

        bulkDeleteButton(fixture)!.click();
        for (const id of [1, 2]) {
            http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}${id}/` }).flush(null, {
                status: 404,
                statusText: 'Not Found',
            });
        }

        expect(toasts.shown).toEqual([{ type: 'info', message: '2 were already deleted: OpenAI key, Anthropic key.' }]);
        answerListLoad(http, []);
        http.verify();
    });

    it('shows a generic reason when two failures of the same status give different reasons', () => {
        const { fixture, http, toasts } = render();
        fixture.detectChanges();
        answerListLoad(http, [OPENAI, ANTHROPIC]);
        fixture.detectChanges();
        selectAllRows(fixture);

        bulkDeleteButton(fixture)!.click();
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}1/` }).flush(
            { message: 'This secret is locked.' },
            { status: 400, statusText: 'Bad Request' }
        );
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}2/` }).flush(
            { message: 'This secret is managed by an integration.' },
            { status: 400, statusText: 'Bad Request' }
        );

        expect(toasts.shown).toEqual([
            {
                type: 'error',
                message: "Couldn't delete 2 secrets. Something went wrong. Not deleted: OpenAI key, Anthropic key.",
            },
        ]);
        answerListLoad(http, [OPENAI, ANTHROPIC]);
        http.verify();
    });

    it('shows a generic reason when the failures are of different kinds', () => {
        const { fixture, http, toasts } = render();
        fixture.detectChanges();
        answerListLoad(http, [OPENAI, ANTHROPIC]);
        fixture.detectChanges();
        selectAllRows(fixture);

        bulkDeleteButton(fixture)!.click();
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}1/` }).flush(
            { message: 'The database is unavailable.' },
            { status: 500, statusText: 'Server Error' }
        );
        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}2/` }).flush(
            { message: 'You do not have permission.' },
            { status: 403, statusText: 'Forbidden' }
        );

        expect(toasts.shown).toEqual([
            {
                type: 'error',
                message: "Couldn't delete 2 secrets. Something went wrong. Not deleted: OpenAI key, Anthropic key.",
            },
        ]);
        answerListLoad(http, [OPENAI, ANTHROPIC]);
        http.verify();
    });

    it('sends the deletes only once when the button is clicked again while they are in flight', () => {
        const { fixture, http } = render();
        fixture.detectChanges();
        answerListLoad(http, [OPENAI]);
        fixture.detectChanges();
        selectAllRows(fixture);

        bulkDeleteButton(fixture)!.click();
        fixture.detectChanges();
        expect(bulkDeleteButton(fixture)!.disabled).toBe(true);
        fixture.componentInstance.onBulkDelete();

        http.expectOne({ method: 'DELETE', url: `${SECRETS_URL}1/` }).flush(null);
        answerListLoad(http, []);
        http.verify();
    });
});
