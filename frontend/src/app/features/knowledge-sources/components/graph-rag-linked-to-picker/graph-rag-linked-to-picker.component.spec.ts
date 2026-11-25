// Pins the picker's request behaviour: one request on open, debounce on search, infinite-scroll
// collapsing scroll events, per-tab cancellation on tab switch, and the `search_scope=identity`
// contract the backend relies on to narrow the picker's search to label columns.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { ConfigService } from '../../../../services/config';
import { GraphTableData } from '../../models/graph-visualization.model';
import { GraphRagLinkedToPickerComponent, LinkedToSelection } from './graph-rag-linked-to-picker.component';
import { LINKED_TO_PICKER_PAGE_SIZE, LinkedToTargetType } from './linked-to-targets';

const API_URL = 'http://api.test/api/';
const RAG_ID = 7;

function tableUrl(table: LinkedToTargetType, extra = ''): string {
    const base = `page=1&page_size=${LINKED_TO_PICKER_PAGE_SIZE}&search_scope=identity`;
    return `${API_URL}graph-rag/${RAG_ID}/tables/${table}/?${extra ? `${extra}&${base}` : base}`;
}

function buildPage(overrides: Partial<GraphTableData> = {}): GraphTableData {
    return {
        columns: ['id', 'title'],
        rows: Array.from({ length: LINKED_TO_PICKER_PAGE_SIZE }, (_, index) => ({
            id: `row-${index}`,
            title: `Row ${index}`,
        })),
        total: LINKED_TO_PICKER_PAGE_SIZE * 3,
        page: 1,
        page_size: LINKED_TO_PICKER_PAGE_SIZE,
        ...overrides,
    };
}

@Component({
    template: `
        <app-graph-rag-linked-to-picker
            [ragId]="ragId"
            [allowedTargets]="allowed()"
            (picked)="picked.set($event)"
        />
    `,
    imports: [GraphRagLinkedToPickerComponent],
})
class TestHostComponent {
    ragId = RAG_ID;
    allowed = signal<readonly LinkedToTargetType[]>([
        'entities',
        'relationships',
        'communities',
        'community_reports',
        'text_units',
        'documents',
        'covariates',
    ]);
    picked = signal<LinkedToSelection | null>(null);
}

describe('GraphRagLinkedToPickerComponent', () => {
    let fixture: ComponentFixture<TestHostComponent>;
    let host: HTMLElement;
    let httpMock: HttpTestingController;

    function trigger(): HTMLButtonElement {
        return host.querySelector<HTMLButtonElement>('.linked-to-trigger')!;
    }

    function overlayRoot(): HTMLElement {
        // CDK overlay renders into document.body, not the host — reach into the DOM directly.
        return document.body.querySelector<HTMLElement>('.linked-to-popover')!;
    }

    function tabButtons(): HTMLButtonElement[] {
        return Array.from(document.body.querySelectorAll<HTMLButtonElement>('.linked-to-popover__tab'));
    }

    function list(): HTMLElement {
        return document.body.querySelector<HTMLElement>('.linked-to-popover__list')!;
    }

    function openPicker(): void {
        trigger().click();
        fixture.detectChanges();
    }

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            imports: [TestHostComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
            ],
        }).compileComponents();

        fixture = TestBed.createComponent(TestHostComponent);
        httpMock = TestBed.inject(HttpTestingController);
        host = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    });

    afterEach(() => {
        httpMock.verify();
    });

    it('fires exactly one request on open for the first allowed tab', () => {
        openPicker();

        httpMock.expectOne(tableUrl('entities')).flush(buildPage());
        fixture.detectChanges();

        expect(overlayRoot()).not.toBeNull();
        expect(tabButtons().length).toBe(7);
    });

    it('sends search_scope=identity so the backend narrows to label columns', () => {
        openPicker();

        const req = httpMock.expectOne(tableUrl('entities'));
        expect(req.request.params.get('search_scope')).toBe('identity');
        req.flush(buildPage());
    });

    it('collapses repeated scroll events near the bottom into one next-page request', async () => {
        openPicker();
        httpMock.expectOne(tableUrl('entities')).flush(buildPage({ total: 100 }));
        fixture.detectChanges();

        const ul = list();
        // Simulate a list that's scrolled close to the bottom.
        Object.defineProperty(ul, 'scrollHeight', { configurable: true, value: 1000 });
        Object.defineProperty(ul, 'clientHeight', { configurable: true, value: 400 });
        Object.defineProperty(ul, 'scrollTop', { configurable: true, value: 600 });

        for (let i = 0; i < 10; i++) {
            ul.dispatchEvent(new Event('scroll'));
        }
        // Flush the single rAF-collapsed check.
        await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
        fixture.detectChanges();

        const req = httpMock.expectOne(
            `${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=2&page_size=${LINKED_TO_PICKER_PAGE_SIZE}&search_scope=identity`
        );
        req.flush(buildPage({ page: 2 }));
    });

    it("keeps the first tab's request in flight when the user switches to a second tab", () => {
        openPicker();
        const first = httpMock.expectOne(tableUrl('entities'));

        // Switch tabs before the first request resolves.
        tabButtons()[1].click();
        fixture.detectChanges();

        // A new request for the second tab — the first tab's request is NOT cancelled by switchMap
        // across groups: per-tab cancellation only applies within the same tab.
        const second = httpMock.expectOne(tableUrl('relationships'));

        first.flush(buildPage());
        second.flush(buildPage());
        fixture.detectChanges();

        expect(fixture.debugElement.query(By.css('.linked-to-popover'))).not.toBeNull();
    });

    it('debounced search resets to page 1 and fires one request with the term', async () => {
        vi.useFakeTimers();
        try {
            openPicker();
            httpMock.expectOne(tableUrl('entities')).flush(buildPage({ total: 100 }));
            fixture.detectChanges();

            const searchInput = document.body.querySelector<HTMLInputElement>(
                '.linked-to-popover__search .search__input'
            )!;
            searchInput.value = 'foo';
            searchInput.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(300);
            fixture.detectChanges();

            const req = httpMock.expectOne(
                (r) =>
                    r.url === `${API_URL}graph-rag/${RAG_ID}/tables/entities/` &&
                    r.params.get('search') === 'foo' &&
                    r.params.get('page') === '1' &&
                    r.params.get('search_scope') === 'identity'
            );
            req.flush(buildPage({ total: 2 }));
        } finally {
            vi.useRealTimers();
        }
    });
});
