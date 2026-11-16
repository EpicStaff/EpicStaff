// Pins what the graph data-tables view shows and requests as the user picks tables, pages, searches and previews
// documents. Component layer: rendered in a host against HttpTestingController, driven and asserted through the DOM.
import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { ConfigService } from '../../../../services/config';
import { GraphRagDocument } from '../../models/graph-rag-document.model';
import { GraphTableData, GraphTableSummaryItem } from '../../models/graph-visualization.model';
import { GraphRagDocumentsStorageService } from '../../services/graph-rag-documents-storage.service';
import { GraphRagDataTablesComponent } from './graph-rag-data-tables.component';

const API_URL = 'http://api.test/api/';
const RAG_ID = 42;
const SUMMARY_URL = `${API_URL}graph-rag/${RAG_ID}/table-summary/`;
const NOT_INDEXED_BODY = { status_code: 409, code: 'graph_not_indexed', message: 'Graph is not indexed' };
const CONFLICT_BODY = { status_code: 409, code: 'upstream_resource_conflict', message: 'Upstream conflict' };

function tableUrl(table: string, query = 'page=1&page_size=10'): string {
    return `${API_URL}graph-rag/${RAG_ID}/tables/${table}/?${query}`;
}

function buildSummary(overrides: Partial<GraphTableSummaryItem>[] = []): GraphTableSummaryItem[] {
    const defaults: GraphTableSummaryItem[] = [
        { name: 'entities', label: 'Entities', count: 37 },
        { name: 'relationships', label: 'Relationships', count: 12 },
        { name: 'documents', label: 'Documents', count: 0 },
    ];
    if (overrides.length) {
        return overrides.map((override, index) => ({
            ...defaults[Math.min(index, defaults.length - 1)],
            ...override,
        }));
    }
    return defaults;
}

function buildTableData(overrides: Partial<GraphTableData> = {}): GraphTableData {
    return {
        columns: ['id', 'title', 'type', 'description', 'degree'],
        rows: [
            { id: 'e1', title: 'Entity 1', type: 'PERSON', description: 'Desc 1', degree: 3 },
            { id: 'e2', title: 'Entity 2', type: 'ORG', description: 'Desc 2', degree: 5 },
        ],
        total: 2,
        page: 1,
        page_size: 10,
        ...overrides,
    };
}

// jsdom has no ResizeObserver; the select's overflow-tooltip directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({
    template: `<app-graph-rag-data-tables [ragId]="ragId" />`,
    imports: [GraphRagDataTablesComponent],
})
class TestHostComponent {
    ragId = RAG_ID;
}

describe('GraphRagDataTablesComponent', () => {
    let fixture: ComponentFixture<TestHostComponent>;
    let httpMock: HttpTestingController;
    let host: HTMLElement;

    /** Flushes the initial table-summary request and the table-data request for the first table with data. */
    function flushInit(
        summary: GraphTableSummaryItem[] = buildSummary(),
        tableData: GraphTableData = buildTableData()
    ): void {
        httpMock.expectOne(SUMMARY_URL).flush(summary);
        const firstWithData = summary.find((item) => item.count > 0) ?? summary[0];
        if (firstWithData) {
            httpMock.expectOne(tableUrl(firstWithData.name)).flush(tableData);
        }
        fixture.detectChanges();
    }

    function text(): string {
        return host.textContent ?? '';
    }

    function gridRows(): HTMLElement[] {
        return Array.from(host.querySelectorAll<HTMLElement>('.grid-table-body .grid-table-row'));
    }

    function headerLabels(): string[] {
        return Array.from(host.querySelectorAll('.grid-table-header .grid-table-col-label')).map(
            (label) => label.textContent?.trim() ?? ''
        );
    }

    function activeCardLabel(): string | undefined {
        return host.querySelector('.data-tables__card--active .data-tables__card-label')?.textContent?.trim();
    }

    function pageButtons(): string[] {
        return Array.from(host.querySelectorAll('.data-tables__pager-btn:not(.data-tables__pager-btn--nav)')).map(
            (button) => button.textContent?.trim() ?? ''
        );
    }

    function activePage(): string | undefined {
        return host.querySelector('.data-tables__pager-btn--active')?.textContent?.trim();
    }

    function navButton(label: 'Previous page' | 'Next page'): HTMLButtonElement {
        return host.querySelector<HTMLButtonElement>(`.data-tables__pager-btn--nav[aria-label="${label}"]`)!;
    }

    function clickPage(page: string): void {
        Array.from(host.querySelectorAll<HTMLButtonElement>('.data-tables__pager-btn'))
            .find((button) => button.textContent?.trim() === page)!
            .click();
        fixture.detectChanges();
    }

    function clickSidebarCard(label: string): void {
        Array.from(host.querySelectorAll<HTMLButtonElement>('.data-tables__card-button'))
            .find((card) => card.textContent?.includes(label))!
            .click();
        fixture.detectChanges();
    }

    function chooseRowsPerPage(label: string): void {
        host.querySelector<HTMLButtonElement>('.data-tables__page-size-select .selector__btn')!.click();
        fixture.detectChanges();
        const overlay = TestBed.inject(OverlayContainer).getContainerElement();
        Array.from(overlay.querySelectorAll<HTMLElement>('.selector__option'))
            .find((option) => option.textContent?.trim() === label)!
            .click();
        fixture.detectChanges();
    }

    function searchInput(): HTMLInputElement {
        return host.querySelector<HTMLInputElement>('.search__input')!;
    }

    function loadingSpinnerShown(): boolean {
        return fixture.debugElement.query(By.css('.data-tables__state app-loading-spinner')) !== null;
    }

    beforeEach(async () => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
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
        vi.unstubAllGlobals();
    });

    describe('tables', () => {
        it('lists the summary tables and shows the first table with data', () => {
            flushInit();

            expect(host.querySelectorAll('.data-tables__card').length).toBe(3);
            expect(activeCardLabel()).toBe('Entities');
            expect(host.querySelector('.data-tables__title')?.textContent?.trim()).toBe('Entities');
        });

        it('opens the first table with data, skipping empty tables', () => {
            flushInit(
                buildSummary([
                    { name: 'documents', label: 'Documents', count: 0 },
                    { name: 'entities', label: 'Entities', count: 5 },
                ])
            );

            expect(activeCardLabel()).toBe('Entities');
        });

        it('renders the columns and rows from the API response in the grid', () => {
            flushInit();

            expect(headerLabels()).toEqual(['Id', 'Title', 'Type', 'Description', 'Degree']);
            expect(gridRows().length).toBe(2);
            expect(gridRows()[1].textContent).toContain('Entity 2');
        });

        it('shows the grid with no rows and no search message for an empty table', () => {
            flushInit(buildSummary(), buildTableData({ rows: [], total: 0 }));

            expect(headerLabels().length).toBe(5);
            expect(gridRows().length).toBe(0);
            expect(text()).not.toContain('No rows match your search');
        });

        it('dims the cards of tables with zero entries', () => {
            flushInit();

            const dimmedLabels = Array.from(
                host.querySelectorAll('.data-tables__card--dimmed .data-tables__card-label')
            ).map((label) => label.textContent?.trim());
            expect(dimmedLabels).toEqual(['Documents']);
        });

        it('switches to the clicked table and loads its first page', () => {
            flushInit(buildSummary(), buildTableData({ total: 25 }));
            clickPage('2');
            httpMock.expectOne(tableUrl('entities', 'page=2&page_size=10')).flush(buildTableData({ total: 25 }));
            fixture.detectChanges();

            clickSidebarCard('Relationships');
            httpMock.expectOne(tableUrl('relationships')).flush(
                buildTableData({
                    columns: ['id', 'source', 'target', 'description', 'weight'],
                    rows: [{ id: 'r1', source: 'A', target: 'B', description: 'link', weight: 1 }],
                    total: 1,
                })
            );
            fixture.detectChanges();

            expect(activeCardLabel()).toBe('Relationships');
            expect(headerLabels()).toEqual(['Id', 'Source', 'Target', 'Description', 'Weight']);
            expect(activePage()).toBe('1');
        });
    });

    describe('pagination', () => {
        it('shows one page button per page of results', () => {
            flushInit(buildSummary(), buildTableData({ total: 25 }));

            expect(pageButtons()).toEqual(['1', '2', '3']);
            expect(activePage()).toBe('1');
        });

        it('loads the next page from the Next button', () => {
            flushInit(buildSummary(), buildTableData({ total: 25 }));

            navButton('Next page').click();
            fixture.detectChanges();
            httpMock
                .expectOne(tableUrl('entities', 'page=2&page_size=10'))
                .flush(buildTableData({ page: 2, total: 25 }));
            fixture.detectChanges();

            expect(activePage()).toBe('2');
        });

        it('disables Previous on the first page and Next on the last page', () => {
            flushInit(buildSummary(), buildTableData({ total: 5 }));

            expect(navButton('Previous page').disabled).toBe(true);
            expect(navButton('Next page').disabled).toBe(true);
            expect(pageButtons()).toEqual(['1']);
        });

        it('goes back to page 1 with the chosen page size when the rows per page change', () => {
            flushInit(buildSummary(), buildTableData({ total: 50 }));
            clickPage('3');
            httpMock.expectOne(tableUrl('entities', 'page=3&page_size=10')).flush(buildTableData({ total: 50 }));
            fixture.detectChanges();

            chooseRowsPerPage('25');
            httpMock
                .expectOne(tableUrl('entities', 'page=1&page_size=25'))
                .flush(buildTableData({ page_size: 25, total: 50 }));
            fixture.detectChanges();

            expect(activePage()).toBe('1');
            expect(pageButtons()).toEqual(['1', '2']);
        });
    });

    describe('errors', () => {
        it('shows an error when the table data request fails', () => {
            httpMock.expectOne(SUMMARY_URL).flush(buildSummary());
            httpMock.expectOne(tableUrl('entities')).flush('Server error', { status: 500, statusText: 'Server Error' });
            fixture.detectChanges();

            expect(text()).toContain('Failed to load table data');
        });

        it('shows an error when the table summary request fails', () => {
            httpMock.expectOne(SUMMARY_URL).flush('Server error', { status: 500, statusText: 'Server Error' });
            fixture.detectChanges();

            expect(text()).toContain('Failed to load table summary');
        });

        it('shows the run-indexing hint when the summary answers 409 graph_not_indexed', () => {
            httpMock.expectOne(SUMMARY_URL).flush(NOT_INDEXED_BODY, { status: 409, statusText: 'Conflict' });
            fixture.detectChanges();

            expect(text()).toContain('run indexing first');
            expect(fixture.debugElement.query(By.css('app-loading-spinner'))).toBeNull();
        });

        it('shows the run-indexing hint when a table answers 409 graph_not_indexed', () => {
            httpMock.expectOne(SUMMARY_URL).flush(buildSummary());
            httpMock.expectOne(tableUrl('entities')).flush(NOT_INDEXED_BODY, { status: 409, statusText: 'Conflict' });
            fixture.detectChanges();

            expect(text()).toContain('run indexing first');
        });

        it.each<[string, number, object]>([
            ['a 409 with another code', 409, CONFLICT_BODY],
            ['a 404', 404, { message: 'missing' }],
        ])('shows a plain error, not the indexing hint, when the summary answers %s', (_label, status, body) => {
            httpMock.expectOne(SUMMARY_URL).flush(body, { status, statusText: 'Error' });
            fixture.detectChanges();

            expect(text()).toContain('Failed to load table summary');
            expect(text()).not.toContain('run indexing first');
        });

        it('replaces the error with the loading state while the next table loads, then shows its rows', () => {
            httpMock.expectOne(SUMMARY_URL).flush(buildSummary());
            httpMock.expectOne(tableUrl('entities')).flush('Server error', { status: 500, statusText: 'Server Error' });
            fixture.detectChanges();

            clickSidebarCard('Relationships');

            expect(loadingSpinnerShown()).toBe(true);
            expect(text()).not.toContain('Failed to load table data');

            httpMock.expectOne(tableUrl('relationships')).flush(buildTableData());
            fixture.detectChanges();

            expect(loadingSpinnerShown()).toBe(false);
            expect(gridRows().length).toBe(2);
        });
    });

    describe('search', () => {
        beforeEach(() => vi.useFakeTimers());
        afterEach(() => vi.useRealTimers());

        function typeSearch(term: string): void {
            const input = searchInput();
            input.value = term;
            input.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(300);
            fixture.detectChanges();
        }

        it('limits the search field to 200 characters', () => {
            flushInit();

            expect(searchInput().getAttribute('maxlength')).toBe('200');
        });

        it('sends the trimmed term and highlights it in the rows', () => {
            flushInit();

            typeSearch('  Entity  ');
            httpMock.expectOne(tableUrl('entities', 'page=1&page_size=10&search=Entity')).flush(buildTableData());
            fixture.detectChanges();

            const marks = Array.from(host.querySelectorAll('mark.grid-table-highlight')).map(
                (mark) => mark.textContent
            );
            expect(marks).toEqual(['Entity', 'Entity']);
        });

        it('says no rows match when a search returns nothing', () => {
            flushInit();

            typeSearch('zzz');
            httpMock
                .expectOne(tableUrl('entities', 'page=1&page_size=10&search=zzz'))
                .flush(buildTableData({ rows: [], total: 0 }));
            fixture.detectChanges();

            expect(text()).toContain('No rows match your search');
            expect(host.querySelector('app-graph-rag-grid-table')).toBeNull();
            // The field stays, so the search can be changed or cleared.
            expect(searchInput()).not.toBeNull();
        });

        it('searches again with the same term after switching tables', () => {
            flushInit();

            typeSearch('alpha');
            httpMock.expectOne(tableUrl('entities', 'page=1&page_size=10&search=alpha')).flush(buildTableData());
            fixture.detectChanges();

            clickSidebarCard('Relationships');
            httpMock.expectOne(tableUrl('relationships')).flush(buildTableData());
            fixture.detectChanges();

            typeSearch('alpha');
            httpMock.expectOne(tableUrl('relationships', 'page=1&page_size=10&search=alpha')).flush(buildTableData());
        });
    });

    describe('document preview', () => {
        const graphRagDocument: GraphRagDocument = {
            graph_rag_document_id: 1,
            document_id: 7,
            file_name: 'report.txt',
            file_size: 10,
            status: 'completed',
            created_at: '2026-01-01T00:00:00Z',
        };
        const previewUrl = `${API_URL}documents/${graphRagDocument.document_id}/preview/`;

        function previewArea() {
            return fixture.debugElement.query(By.css('.data-tables__preview'));
        }

        function clickDocumentRow(): void {
            fixture.debugElement.query(By.css('[role="gridcell"]')).nativeElement.click();
            fixture.detectChanges();
        }

        beforeEach(() => {
            TestBed.inject(GraphRagDocumentsStorageService).setDocuments([graphRagDocument]);
            flushInit(
                buildSummary([{ name: 'documents', label: 'Documents', count: 1 }]),
                buildTableData({ columns: ['id', 'title'], rows: [{ id: 'd1', title: 'report.txt' }], total: 1 })
            );
        });

        it('clears the loading state after a failed preview and loads a later preview', () => {
            clickDocumentRow();
            expect(previewArea().query(By.css('app-loading-spinner'))).not.toBeNull();

            httpMock
                .expectOne(previewUrl)
                .flush(new Blob(['boom']), { status: 500, statusText: 'Internal Server Error' });
            fixture.detectChanges();

            expect(previewArea().query(By.css('app-loading-spinner'))).toBeNull();
            expect(previewArea().nativeElement.textContent).toContain('Failed to load document preview.');

            fixture.debugElement.query(By.css('.data-tables__breadcrumb-back')).nativeElement.click();
            fixture.detectChanges();
            clickDocumentRow();

            httpMock.expectOne(previewUrl).flush(new Blob(['hello'], { type: 'text/plain' }));
            fixture.detectChanges();

            expect(previewArea().query(By.css('app-loading-spinner'))).toBeNull();
            expect(previewArea().nativeElement.textContent).not.toContain('Failed to load document preview.');
            expect(previewArea().query(By.css('app-blob-preview'))).not.toBeNull();
        });
    });
});
