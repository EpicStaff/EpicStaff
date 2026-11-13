import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { ConfigService } from '../../../../services/config';
import { GraphTableData, GraphTableSummaryItem } from '../../models/graph-visualization.model';
import { GraphRagDataTablesComponent } from './graph-rag-data-tables.component';
import { HighlightPipe } from './highlight.pipe';

const API_URL = 'http://api.test/api/';
const RAG_ID = 42;

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
    let component: GraphRagDataTablesComponent;

    /** Flushes the initial table-summary request and the subsequent table-data request. */
    function flushInit(
        summary: GraphTableSummaryItem[] = buildSummary(),
        tableData: GraphTableData = buildTableData()
    ): void {
        httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/table-summary/`).flush(summary);
        const firstWithData = summary.find((s) => s.count > 0) ?? summary[0];
        if (firstWithData) {
            httpMock
                .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/${firstWithData.name}/?page=1&page_size=10`)
                .flush(tableData);
        }
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
        fixture.detectChanges();

        component = fixture.debugElement.query(By.directive(GraphRagDataTablesComponent))
            .componentInstance as GraphRagDataTablesComponent;
    });

    afterEach(() => httpMock.verify());

    it('fetches table summary and first table data on init', () => {
        flushInit();
        expect(component.tables().length).toBe(3);
        expect(component.activeTable()?.name).toBe('entities');
        expect(component.viewState()).toBe('ready');
    });

    it('auto-selects first table with data, skipping empty tables', () => {
        const summary = buildSummary([
            { name: 'documents', label: 'Documents', count: 0 },
            { name: 'entities', label: 'Entities', count: 5 },
        ]);
        httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/table-summary/`).flush(summary);
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData());

        expect(component.activeTable()?.name).toBe('entities');
    });

    it('shows ready state and populates rows and columns after a successful response', () => {
        const data = buildTableData();
        flushInit(buildSummary(), data);

        expect(component.viewState()).toBe('ready');
        expect(component.rows()).toEqual(data.rows);
        expect(component.columns()).toEqual(data.columns);
        expect(component.total()).toBe(2);
    });

    it('shows empty state when total is 0', () => {
        flushInit(buildSummary(), buildTableData({ rows: [], total: 0 }));
        expect(component.viewState()).toBe('empty');
    });

    it('shows error state on table data HTTP failure', () => {
        httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/table-summary/`).flush(buildSummary());
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush('Server error', { status: 500, statusText: 'Internal Server Error' });

        expect(component.viewState()).toBe('error');
        expect(component.errorMessage()).toBe('Failed to load table data');
    });

    it('shows error state on table summary HTTP failure', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/table-summary/`)
            .flush('Server error', { status: 500, statusText: 'Internal Server Error' });

        expect(component.viewState()).toBe('error');
        expect(component.errorMessage()).toBe('Failed to load table summary');
    });

    it('switches table, resets page and search', () => {
        flushInit();

        const relationships = component.tables().find((t) => t.name === 'relationships')!;
        component.onSelectTable(relationships);

        expect(component.activeTable()?.name).toBe('relationships');
        expect(component.page()).toBe(1);
        expect(component.searchTerm()).toBe('');

        const request = httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/relationships/?page=1&page_size=10`);
        expect(request.request.method).toBe('GET');
        request.flush(
            buildTableData({
                columns: ['id', 'source', 'target', 'description', 'weight'],
                rows: [{ id: 'r1', source: 'A', target: 'B', description: 'link', weight: 1 }],
                total: 1,
            })
        );
    });

    it('navigates to the next page', () => {
        flushInit(buildSummary(), buildTableData({ total: 25 }));

        component.onPageChange(2);
        expect(component.page()).toBe(2);

        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=2&page_size=10`)
            .flush(buildTableData({ page: 2, total: 25 }));
    });

    it('ignores page change below 1', () => {
        flushInit();
        component.onPageChange(0);
        expect(component.page()).toBe(1);
    });

    it('ignores page change beyond total pages', () => {
        flushInit(buildSummary(), buildTableData({ total: 5 }));
        component.onPageChange(2);
        expect(component.page()).toBe(1);
    });

    it('computes totalPages correctly', () => {
        flushInit(buildSummary(), buildTableData({ total: 25 }));
        expect(component.totalPages()).toBe(3);
    });

    it('changes page size and resets to page 1', () => {
        flushInit(buildSummary(), buildTableData({ total: 50 }));
        component.page.set(3);

        component.onPageSizeChange({ target: { value: '25' } } as unknown as Event);
        expect(component.pageSize()).toBe(25);
        expect(component.page()).toBe(1);

        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=25`)
            .flush(buildTableData({ page_size: 25, total: 50 }));
    });

    it('renders sidebar cards with correct count', () => {
        flushInit();
        fixture.detectChanges();

        const cards = fixture.debugElement.queryAll(By.css('.data-tables__card'));
        expect(cards.length).toBe(3);
    });

    it('marks the active sidebar card', () => {
        flushInit();
        fixture.detectChanges();

        const activeCard = fixture.debugElement.query(By.css('.data-tables__card--active'));
        expect(activeCard).toBeTruthy();
        const label = activeCard.query(By.css('.data-tables__card-label'));
        expect(label.nativeElement.textContent.trim()).toBe('Entities');
    });

    it('dims cards with zero entries', () => {
        flushInit();
        fixture.detectChanges();

        const dimmedCards = fixture.debugElement.queryAll(By.css('.data-tables__card--dimmed'));
        expect(dimmedCards.length).toBe(1);
        const label = dimmedCards[0].query(By.css('.data-tables__card-label'));
        expect(label.nativeElement.textContent.trim()).toBe('Documents');
    });

    it('renders dynamic column headers from API response', () => {
        flushInit();
        fixture.detectChanges();

        const headers = fixture.debugElement.queryAll(By.css('.data-tables__table th'));
        expect(headers.length).toBe(5);
        expect(headers[0].nativeElement.textContent.trim()).toBe('Id');
        expect(headers[3].nativeElement.textContent.trim()).toBe('Description');
    });

    it('renders table rows in the DOM', () => {
        flushInit();
        fixture.detectChanges();

        const tableRows = fixture.debugElement.queryAll(By.css('.data-tables__table tbody tr'));
        expect(tableRows.length).toBe(2);
    });

    it('opens cell overlay on double-click and closes on Esc', () => {
        flushInit();
        fixture.detectChanges();

        component.onCellDoubleClick('description', 'Full description text');
        expect(component.expandedCell()).toEqual({ column: 'description', value: 'Full description text' });

        fixture.detectChanges();
        const overlay = fixture.debugElement.query(By.css('.data-tables__overlay'));
        expect(overlay).toBeTruthy();
        const title = overlay.query(By.css('.data-tables__overlay-header-title'));
        expect(title.nativeElement.textContent.trim()).toBe('Description');

        component.onEscapeKey();
        expect(component.expandedCell()).toBeNull();
    });

    it('formats column headers by capitalizing and replacing underscores', () => {
        expect(component.formatColumnHeader('human_readable_id')).toBe('Human Readable Id');
        expect(component.formatColumnHeader('title')).toBe('Title');
    });

    it('shows tables-with-data count in sidebar header', () => {
        flushInit();
        fixture.detectChanges();

        expect(component.tablesWithDataCount()).toBe(2);
        const count = fixture.debugElement.query(By.css('.data-tables__sidebar-count'));
        expect(count.nativeElement.textContent.trim()).toBe('2');
    });
});

describe('HighlightPipe', () => {
    const pipe = new HighlightPipe();

    it('returns escaped text when no search term', () => {
        expect(pipe.transform('Hello <World>', '')).toBe('Hello &lt;World&gt;');
    });

    it('wraps matching text in mark tags', () => {
        const result = pipe.transform('Hello World', 'world');
        expect(result).toBe('Hello <mark class="data-tables__highlight">World</mark>');
    });

    it('is case-insensitive', () => {
        const result = pipe.transform('Hello WORLD', 'world');
        expect(result).toBe('Hello <mark class="data-tables__highlight">WORLD</mark>');
    });

    it('escapes HTML in value before highlighting to prevent XSS', () => {
        const result = pipe.transform('<script>alert("xss")</script>', 'script');
        expect(result).toContain('&lt;');
        expect(result).toContain('&gt;');
        expect(result).not.toContain('<script>');
    });

    it('handles null and undefined values', () => {
        expect(pipe.transform(null, 'test')).toBe('');
        expect(pipe.transform(undefined, 'test')).toBe('');
    });

    it('escapes regex special characters in search term', () => {
        const result = pipe.transform('price is $10.00', '$10.00');
        expect(result).toContain('<mark class="data-tables__highlight">$10.00</mark>');
    });
});
