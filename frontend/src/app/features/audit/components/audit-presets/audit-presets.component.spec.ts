import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../../services/config';
import { EMPTY_AUDIT_FILTER } from '../../models/audit-filter.models';
import { AuditPreset } from '../../models/audit-preset.models';
import { AuditPresetsStorageService } from '../../services/audit-presets-storage.service';
import { buildPresetBody } from '../../utils/audit-preset-body.util';
import { AuditPresetsComponent } from './audit-presets.component';

const PRESETS_URL = '/api/audit-filter-presets/';
const EXPORT_JOBS_URL = '/api/audit-filter-presets/export-jobs/';

function preset(id: number, name: string): AuditPreset {
    return {
        id,
        name,
        filter_body: buildPresetBody(EMPTY_AUDIT_FILTER),
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

    it('exports one preset from its menu as a background job', () => {
        click(element.querySelector<HTMLButtonElement>('[aria-label="More actions for Slow"]')!);
        click(buttonWithText(TestBed.inject(OverlayContainer).getContainerElement(), 'Export'));

        expect(httpMock.expectOne(EXPORT_JOBS_URL).request.body).toEqual({ ids: [2] });
    });

    it('exports the selected presets in one job and ends selecting once the server has taken it', () => {
        click(buttonWithText(element, 'Export'));
        click(element.querySelector<HTMLInputElement>('input[aria-label="Select all presets"]')!);
        click(buttonWithText(element, 'Export'));

        const start = httpMock.expectOne(EXPORT_JOBS_URL);
        expect(start.request.body).toEqual({ ids: [1, 2] });
        expect(element.textContent).toContain('2 selected');

        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        fixture.detectChanges();

        expect(element.textContent).not.toContain('2 selected');
    });

    it('accepts a .zip export as well as a plain .json one in the import picker', () => {
        expect(element.querySelector<HTMLInputElement>('input[type="file"]')!.accept).toBe('.json,.zip');
    });
});
