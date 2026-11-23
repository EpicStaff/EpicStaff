import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../../services/config';
import { AUDIT_FIELD_CATALOG } from '../../models/audit-domain.models';
import { EMPTY_AUDIT_FILTER } from '../../models/audit-filter.models';
import { AuditPreset } from '../../models/audit-preset.models';
import { USER_ACTION_FIELD_CATALOG } from '../../models/audit-user-action-filter-options';
import { AuditPresetsStorageService } from '../../services/audit-presets-storage.service';
import { buildPresetBody } from '../../utils/audit-preset-body.util';
import { AuditPresetsComponent } from './audit-presets.component';

const PRESETS_URL = '/api/audit-filter-presets/';
const EXPORT_JOBS_URL = '/api/audit-filter-presets/export-jobs/';
const JOB_URL = '/api/transfer-jobs/job-1/';

function preset(id: number, name: string): AuditPreset {
    return {
        id,
        name,
        filter_body: buildPresetBody(EMPTY_AUDIT_FILTER, USER_ACTION_FIELD_CATALOG),
        is_owner: true,
        is_shared: false,
        created_by_name: 'Ivan Bohun',
        created_at: '2026-11-06T10:00:00Z',
        updated_at: '2026-11-06T10:00:00Z',
    };
}

// jsdom has no ResizeObserver; the overflow tooltips only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('AuditPresetsComponent export and import', () => {
    let fixture: ComponentFixture<AuditPresetsComponent>;
    let element: HTMLElement;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            imports: [AuditPresetsComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                // A tab other than the server's default domain, so a request that drops the domain is caught.
                { provide: AUDIT_FIELD_CATALOG, useValue: USER_ACTION_FIELD_CATALOG },
                // The filters panel provides it to both preset tabs.
                AuditPresetsStorageService,
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        TestBed.inject(AuditPresetsStorageService).load();
        httpMock
            .expectOne((request) => request.url === PRESETS_URL)
            .flush({ count: 2, next: null, previous: null, results: [preset(1, 'Failures'), preset(2, 'Slow')] });

        fixture = TestBed.createComponent(AuditPresetsComponent);
        fixture.componentRef.setInput('scope', 'mine');
        fixture.componentRef.setInput('currentFilter', EMPTY_AUDIT_FILTER);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    });

    afterEach(() => {
        httpMock.verify();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    function buttonWithText(container: ParentNode, text: string): HTMLButtonElement {
        const found = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent?.trim() === text
        );
        if (!found) throw new Error(`No "${text}" button`);
        return found;
    }

    function click(target: HTMLElement): void {
        target.click();
        fixture.detectChanges();
    }

    function startSelectedExport(): ReturnType<HttpTestingController['expectOne']> {
        click(buttonWithText(element, 'Export'));
        click(element.querySelector<HTMLInputElement>('input[aria-label="Select all presets"]')!);
        click(buttonWithText(element, 'Export'));
        return httpMock.expectOne((request) => request.url === EXPORT_JOBS_URL);
    }

    function refuse(start: ReturnType<HttpTestingController['expectOne']>): void {
        start.flush(
            { type: 'client_error', errors: [{ code: 'too_many_jobs', detail: 'Busy.', attr: null, context: null }] },
            { status: 429, statusText: 'Too Many Requests' }
        );
        fixture.detectChanges();
    }

    it('exports one preset from its menu as a background job', () => {
        click(element.querySelector<HTMLButtonElement>('[aria-label="More actions for Slow"]')!);
        click(buttonWithText(TestBed.inject(OverlayContainer).getContainerElement(), 'Export'));

        const start = httpMock.expectOne((request) => request.url === EXPORT_JOBS_URL);
        expect(start.request.body).toEqual({ ids: [2] });
        expect(start.request.params.get('domain')).toBe('user_actions');
        // Refused, so no job is polled after the test.
        refuse(start);
    });

    it('exports the selected presets in one job and ends selecting once the server has taken it', async () => {
        const start = startSelectedExport();
        expect(start.request.body).toEqual({ ids: [1, 2] });
        expect(start.request.params.get('domain')).toBe('user_actions');
        expect(element.textContent).toContain('2 selected');

        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        fixture.detectChanges();

        expect(element.textContent).not.toContain('2 selected');
        // Ends the job's wait, so no poll is left open after the test.
        const poll = await vi.waitFor(() => httpMock.expectOne(JOB_URL));
        poll.flush({ id: 'job-1', kind: 'export', status: 'failed', error: 'Stopped by the test.' });
    });

    it('keeps the selection when the server refuses to start the export', () => {
        refuse(startSelectedExport());

        expect(element.textContent).toContain('2 selected');
        expect(buttonWithText(element, 'Export').disabled).toBe(false);
    });
});

describe('AuditPresetsComponent save errors', () => {
    let fixture: ComponentFixture<AuditPresetsComponent>;
    let element: HTMLElement;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            imports: [AuditPresetsComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: AUDIT_FIELD_CATALOG, useValue: USER_ACTION_FIELD_CATALOG },
                AuditPresetsStorageService,
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        TestBed.inject(AuditPresetsStorageService).load();
        httpMock
            .expectOne((request) => request.url === PRESETS_URL)
            .flush({ count: 0, next: null, previous: null, results: [] });

        fixture = TestBed.createComponent(AuditPresetsComponent);
        fixture.componentRef.setInput('scope', 'mine');
        fixture.componentRef.setInput('currentFilter', EMPTY_AUDIT_FILTER);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    });

    afterEach(() => {
        httpMock.verify();
        vi.unstubAllGlobals();
    });

    function saveNewPreset(name: string): ReturnType<HttpTestingController['expectOne']> {
        const buttons = (): HTMLButtonElement[] => Array.from(element.querySelectorAll<HTMLButtonElement>('button'));
        buttons()
            .find((button) => button.textContent?.trim() === 'New Preset')!
            .click();
        fixture.detectChanges();
        const nameInput = element.querySelector<HTMLInputElement>('#audit-preset-name')!;
        nameInput.value = name;
        nameInput.dispatchEvent(new Event('input'));
        fixture.detectChanges();
        buttons()
            .find((button) => button.textContent?.trim() === 'Save Changes')!
            .click();
        return httpMock.expectOne((request) => request.method === 'POST' && request.url === PRESETS_URL);
    }

    function shownError(): string | undefined {
        return element.querySelector('.preset-form__error')?.textContent?.trim();
    }

    it('shows the first reason of a refused save, without its field label', () => {
        const body = {
            type: 'validation_error',
            errors: [
                { code: 'unique', detail: 'A preset with this name already exists.', attr: 'name' },
                { code: 'invalid', detail: 'Bad.', attr: 'filter_body' },
            ],
        };
        saveNewPreset('Failures').flush(body, { status: 400, statusText: 'Bad Request' });
        fixture.detectChanges();

        expect(shownError()).toBe('A preset with this name already exists.');
    });

    it('shows its own words for a failure that is not a refused field', () => {
        saveNewPreset('Failures').flush(
            {
                type: 'server_error',
                errors: [{ code: 'error', detail: 'Unpredictable error', attr: null, context: null }],
            },
            { status: 500, statusText: 'Server Error' }
        );
        fixture.detectChanges();

        expect(shownError()).toBe('Could not save the preset.');
    });
});
