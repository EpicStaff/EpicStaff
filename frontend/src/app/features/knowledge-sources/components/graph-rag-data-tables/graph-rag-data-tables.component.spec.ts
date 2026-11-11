import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { ConfigService } from '../../../../services/config';
import { GraphTableData } from '../../models/graph-visualization.model';
import { GraphRagDataTablesComponent } from './graph-rag-data-tables.component';

const API_URL = 'http://api.test/api/';
const RAG_ID = 42;

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

    it('fetches the first table (entities) on init', () => {
        const request = httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`);
        expect(request.request.method).toBe('GET');
        request.flush(buildTableData());
    });

    it('transitions to loading state while fetching', () => {
        expect(component.viewState()).toBe('loading');
        const request = httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`);
        request.flush(buildTableData());
        expect(component.viewState()).toBe('ready');
    });

    it('shows ready state and populates rows after a successful response', () => {
        const data = buildTableData();
        httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`).flush(data);

        expect(component.viewState()).toBe('ready');
        expect(component.rows()).toEqual(data.rows);
        expect(component.total()).toBe(2);
    });

    it('shows empty state when total is 0', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData({ rows: [], total: 0 }));

        expect(component.viewState()).toBe('empty');
    });

    it('shows error state on HTTP failure', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush('Server error', { status: 500, statusText: 'Internal Server Error' });

        expect(component.viewState()).toBe('error');
        expect(component.errorMessage()).toBe('Failed to load table data');
    });

    it('switches table and resets page to 1', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData());

        const relationshipsTable = component.tables.find((t) => t.name === 'relationships')!;
        component.onSelectTable(relationshipsTable);

        expect(component.activeTable().name).toBe('relationships');
        expect(component.page()).toBe(1);

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
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData({ total: 25 }));

        component.onPageChange(2);
        expect(component.page()).toBe(2);

        const request = httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=2&page_size=10`);
        request.flush(buildTableData({ page: 2, total: 25 }));
    });

    it('ignores page change below 1', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData());

        component.onPageChange(0);
        expect(component.page()).toBe(1);
    });

    it('ignores page change beyond total pages', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData({ total: 5 }));

        // total=5, pageSize=10 => totalPages=1
        component.onPageChange(2);
        expect(component.page()).toBe(1);
    });

    it('computes totalPages correctly', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData({ total: 25 }));

        expect(component.totalPages()).toBe(3);
    });

    it('renders table rows in the DOM after data loads', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData());

        fixture.detectChanges();

        const tableRows = fixture.debugElement.queryAll(By.css('.data-tables__table tbody tr'));
        expect(tableRows.length).toBe(2);
    });

    it('renders all 7 sidebar navigation buttons', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData());

        fixture.detectChanges();

        const navButtons = fixture.debugElement.queryAll(By.css('.data-tables__nav-item'));
        expect(navButtons.length).toBe(7);
    });

    it('marks the active sidebar button', () => {
        httpMock
            .expectOne(`${API_URL}graph-rag/${RAG_ID}/tables/entities/?page=1&page_size=10`)
            .flush(buildTableData());

        fixture.detectChanges();

        const activeButton = fixture.debugElement.query(By.css('.data-tables__nav-item--active'));
        expect(activeButton.nativeElement.textContent.trim()).toBe('Entities');
    });
});
