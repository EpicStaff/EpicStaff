import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../../services/config';
import { IndexingUsage } from '../../models/base-rag.model';
import { CreateCollectionDtoResponse } from '../../models/collection.model';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { GraphRagLinkPairsStorageService } from '../../services/graph-rag-link-pairs-storage.service';
import { GraphRagTabbedViewComponent } from './graph-rag-tabbed-view.component';

const API_URL = 'http://api.test/api/';
const RAG_ID = 42;

// jsdom has no ResizeObserver; shared overflow-tooltip directives only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Only the fields `getRagIndexingUsage` reads are meaningful; the rest keeps the cache code happy. */
function buildCollection(indexingUsage: IndexingUsage): CreateCollectionDtoResponse {
    return {
        collection_id: 1,
        collection_name: 'Collection',
        description: null,
        document_count: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        rag_configurations: [{ rag_id: RAG_ID, rag_type: 'graph', indexing_usage: indexingUsage }],
    } as unknown as CreateCollectionDtoResponse;
}

@Component({
    template: `<app-graph-rag-tabbed-view [ragId]="ragId">
        <p class="projected">Config content</p>
    </app-graph-rag-tabbed-view>`,
    imports: [GraphRagTabbedViewComponent],
})
class TestHostComponent {
    readonly ragId = RAG_ID;
}

describe('GraphRagTabbedViewComponent', () => {
    let fixture: ComponentFixture<TestHostComponent>;
    let httpMock: HttpTestingController;

    function tabButton(label: string): HTMLButtonElement {
        const buttons = Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button.tab-btn')
        );
        return buttons.find((button) => button.textContent?.includes(label))!;
    }

    function query(selector: string): Element | null {
        return (fixture.nativeElement as HTMLElement).querySelector(selector);
    }

    function render(indexingUsage: IndexingUsage | null): void {
        if (indexingUsage) {
            TestBed.inject(CollectionsStorageService).updateOrCreateCollectionInCache(buildCollection(indexingUsage));
        }
        TestBed.inject(GraphRagLinkPairsStorageService).resetForTesting();
        fixture = TestBed.createComponent(TestHostComponent);
        httpMock = TestBed.inject(HttpTestingController);
        fixture.detectChanges();
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
    });

    afterEach(() => {
        httpMock.verify();
        vi.unstubAllGlobals();
    });

    it('disables the graph tabs and shows the configuration before indexing has run', () => {
        render(null);

        expect(tabButton('Graph Visualization').disabled).toBe(true);
        expect(tabButton('Data Tables').disabled).toBe(true);
        expect(query('.projected')).not.toBeNull();
    });

    it('renders the data tables when the Data Tables tab is clicked after indexing', () => {
        render({ total: { embedding_tokens: 10, llm_input_tokens: 5, llm_output_tokens: 5, cost_usd: 0.01 } });
        expect(tabButton('Data Tables').disabled).toBe(false);

        tabButton('Data Tables').click();
        fixture.detectChanges();

        expect(query('app-graph-rag-data-tables')).not.toBeNull();
        expect(query('app-graph-rag-visualization')).toBeNull();
        expect(query('.projected')).toBeNull();
        // The data tables start loading their summary and the link-pairs matrix as soon as they render.
        httpMock.expectOne(`${API_URL}graph-rag/${RAG_ID}/table-summary/`);
        httpMock.expectOne(`${API_URL}graph-rag/table-link-pairs/`);
    });
});
