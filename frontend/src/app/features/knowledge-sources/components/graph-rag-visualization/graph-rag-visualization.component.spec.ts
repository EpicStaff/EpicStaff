import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
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
        description: `Description ${i}`,
        degree: i + 1,
        community_ids: ['c0'],
    }));
    return {
        entities,
        relationships: [{ id: 'r0', source: 'Entity 0', target: 'Entity 1', description: 'knows', weight: 1.0 }],
        communities: [{ id: 'c0', title: 'Community 0', level: 0, size: entityCount, entity_ids: ['e0', 'e1'] }],
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

    it('stays idle until activate() is called', () => {
        // No HTTP request should be made when the component is first rendered
        httpMock.expectNone(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        const vizComponent = fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;
        expect(vizComponent.viewState()).toBe('idle');
    });

    it('sends a GET request with max_entities when activated', () => {
        const vizComponent = fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;

        vizComponent.activate();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        expect(request.request.method).toBe('GET');
        request.flush(buildVisualizationData());
    });

    it('shows loading state while fetching', () => {
        const vizComponent = fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;

        vizComponent.activate();
        expect(vizComponent.viewState()).toBe('loading');

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush(buildVisualizationData());
    });

    it('shows empty state on 404 response', () => {
        const vizComponent = fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;

        vizComponent.activate();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush({ message: 'Not found' }, { status: 404, statusText: 'Not Found' });

        expect(vizComponent.viewState()).toBe('empty');
    });

    it('shows error state on 503 response', () => {
        const vizComponent = fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;

        vizComponent.activate();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush({ message: 'unavailable' }, { status: 503, statusText: 'Service Unavailable' });

        expect(vizComponent.viewState()).toBe('error');
        expect(vizComponent.errorMessage()).toBe('GraphRAG is not available on this server');
    });

    it('shows empty state when API returns zero entities', () => {
        const vizComponent = fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;

        vizComponent.activate();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush({ entities: [], relationships: [], communities: [] });

        expect(vizComponent.viewState()).toBe('empty');
    });

    it('populates counts after successful data load', () => {
        const vizComponent = fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;

        vizComponent.activate();

        const data = buildVisualizationData(5);
        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush(data);

        expect(vizComponent.entityCount()).toBe(5);
        expect(vizComponent.relationshipCount()).toBe(1);
        expect(vizComponent.communityCount()).toBe(1);
    });

    it('builds entity type filters from loaded data', () => {
        const vizComponent = fixture.debugElement.query(By.directive(GraphRagVisualizationComponent))
            .componentInstance as GraphRagVisualizationComponent;

        vizComponent.activate();

        const request = httpMock.expectOne(`${API_URL}graph-rag/42/visualization/?max_entities=200`);
        request.flush(buildVisualizationData(4));

        const filters = vizComponent.entityTypeFilters();
        const labels = filters.map((f) => f.type);
        expect(labels).toContain('PERSON');
        expect(labels).toContain('ORG');
        expect(filters.every((f) => f.checked)).toBe(true);
    });
});
