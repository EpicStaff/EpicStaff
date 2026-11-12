import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, fakeAsync, TestBed, tick } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { ConfigService } from '../../../../services/config';
import { GraphVisualizationData } from '../../models/graph-visualization.model';
import { GraphRagVisualizationComponent } from './graph-rag-visualization.component';

const API_URL = 'http://api.test/api/';

function buildVisualizationData(entityCount = 3): GraphVisualizationData {
    const entities = Array.from({ length: entityCount }, (_, i) => ({
        id: `e${i}`,
        title: `Entity ${i}`,
        type: i % 2 === 0 ? 'PERSON' : 'ORG',
        degree: i + 1,
        community_ids: ['c0'],
    }));
    return {
        entities,
        relationships: [{ id: 'r0', source: 'Entity 0', target: 'Entity 1', weight: 1.0 }],
        total_entities: entityCount,
        total_relationships: 1,
    };
}

@Component({
    template: `<app-graph-rag-visualization [ragId]="ragId" />`,
    imports: [GraphRagVisualizationComponent],
})
class TestHostComponent {
    ragId = 42;
}

describe('GraphRagVisualizationComponent', () => {
    let fixture: ComponentFixture<TestHostComponent>;
    let httpMock: HttpTestingController;

    function getVizComponent(): GraphRagVisualizationComponent {
        return fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;
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
    });

    afterEach(() => httpMock.verify());

    it('sends a GET request with max_entities on init', () => {
        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        expect(request.request.method).toBe('GET');
        request.flush(buildVisualizationData());
    });

    it('shows loading state while fetching', () => {
        const vizComponent = getVizComponent();
        expect(vizComponent.viewState()).toBe('loading');

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush(buildVisualizationData());
    });

    it('shows empty state on 404 response', () => {
        const vizComponent = getVizComponent();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush({ message: 'Not found' }, { status: 404, statusText: 'Not Found' });

        expect(vizComponent.viewState()).toBe('empty');
    });

    it('shows error state on 503 response', () => {
        const vizComponent = getVizComponent();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush({ message: 'unavailable' }, { status: 503, statusText: 'Service Unavailable' });

        expect(vizComponent.viewState()).toBe('error');
        expect(vizComponent.errorMessage()).toBe('GraphRAG is not available on this server');
    });

    it('shows empty state when API returns zero entities', () => {
        const vizComponent = getVizComponent();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush({ entities: [], relationships: [], total_entities: 0, total_relationships: 0 });

        expect(vizComponent.viewState()).toBe('empty');
    });

    it('populates counts after successful data load', () => {
        const vizComponent = getVizComponent();

        const data = buildVisualizationData(5);
        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush(data);

        expect(vizComponent.entityCount()).toBe(5);
        expect(vizComponent.relationshipCount()).toBe(1);
    });

    it('builds entity type filters from loaded data', () => {
        const vizComponent = getVizComponent();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush(buildVisualizationData(4));

        const filters = vizComponent.entityTypeFilters();
        const labels = filters.map((f) => f.type);
        expect(labels).toContain('PERSON');
        expect(labels).toContain('ORG');
        expect(filters.every((f) => f.checked)).toBe(true);
    });

    describe('API-driven search', () => {
        it('sends search param to API after debounce', fakeAsync(() => {
            const vizComponent = getVizComponent();

            // Flush initial load
            const initialRequest = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
            initialRequest.flush(buildVisualizationData());

            vizComponent.onSearchTermChange('test query');
            tick(300);

            const searchRequest = httpMock.expectOne(
                (req) =>
                    req.url === `${API_URL}graph-rag/42/visualization/` &&
                    req.params.get('search') === 'test query' &&
                    req.params.get('max_entities') === '200'
            );
            expect(searchRequest.request.method).toBe('GET');
            searchRequest.flush(buildVisualizationData(2));
        }));

        it('does not send search param when term is whitespace only', fakeAsync(() => {
            const vizComponent = getVizComponent();

            const initialRequest = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
            initialRequest.flush(buildVisualizationData());

            vizComponent.onSearchTermChange('   ');
            tick(300);

            const reloadRequest = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
            expect(reloadRequest.request.params.has('search')).toBe(false);
            reloadRequest.flush(buildVisualizationData());
        }));

        it('debounces rapid search input', fakeAsync(() => {
            const vizComponent = getVizComponent();

            const initialRequest = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
            initialRequest.flush(buildVisualizationData());

            vizComponent.onSearchTermChange('a');
            tick(100);
            vizComponent.onSearchTermChange('ab');
            tick(100);
            vizComponent.onSearchTermChange('abc');
            tick(300);

            // Only the last value should trigger a request
            const searchRequest = httpMock.expectOne(
                (req) => req.url === `${API_URL}graph-rag/42/visualization/` && req.params.get('search') === 'abc'
            );
            searchRequest.flush(buildVisualizationData(1));
        }));

        it('skips duplicate consecutive search terms', fakeAsync(() => {
            const vizComponent = getVizComponent();

            const initialRequest = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
            initialRequest.flush(buildVisualizationData());

            vizComponent.onSearchTermChange('same');
            tick(300);

            const firstSearch = httpMock.expectOne((req) => req.params.get('search') === 'same');
            firstSearch.flush(buildVisualizationData(2));

            // Same term again — should be suppressed by distinctUntilChanged
            vizComponent.onSearchTermChange('same');
            tick(300);

            httpMock.expectNone(`${API_URL}graph-rag/42/visualization/`);
        }));

        it('resets entity type filters when search triggers reload', fakeAsync(() => {
            const vizComponent = getVizComponent();

            const initialRequest = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
            initialRequest.flush(buildVisualizationData(4));

            expect(vizComponent.entityTypeFilters().length).toBeGreaterThan(0);

            vizComponent.onSearchTermChange('person');
            tick(300);

            // Filters should be cleared before the reload
            expect(vizComponent.entityTypeFilters()).toEqual([]);

            const searchRequest = httpMock.expectOne((req) => req.params.get('search') === 'person');
            searchRequest.flush(buildVisualizationData(2));

            // Filters rebuilt from new data
            expect(vizComponent.entityTypeFilters().length).toBeGreaterThan(0);
        }));

        it('includes search param when max entities changes during active search', fakeAsync(() => {
            const vizComponent = getVizComponent();

            const initialRequest = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
            initialRequest.flush(buildVisualizationData());

            // Set a search term via the search flow
            vizComponent.onSearchTermChange('query');
            tick(300);

            const searchRequest = httpMock.expectOne((req) => req.params.get('search') === 'query');
            searchRequest.flush(buildVisualizationData(2));

            // Now change max entities — should still include search
            vizComponent.onMaxEntitiesChange(50);

            const entitiesRequest = httpMock.expectOne(
                (req) =>
                    req.url === `${API_URL}graph-rag/42/visualization/` &&
                    req.params.get('max_entities') === '50' &&
                    req.params.get('search') === 'query'
            );
            entitiesRequest.flush(buildVisualizationData(2));
        }));
    });
});
