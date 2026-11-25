// Pins what the graph visualization shows and requests as data loads, fails, is searched and resized, and that the
// 3D scene is created once and updated in place. Component layer: rendered in a host against HttpTestingController
// with a fake scene service (no WebGL in jsdom), driven and asserted through the DOM.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, Injectable } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { ConfigService } from '../../../../services/config';
import { GraphVisualizationData } from '../../models/graph-visualization.model';
import { GraphRagLinkPairsStorageService } from '../../services/graph-rag-link-pairs-storage.service';
import { GraphRagVisualizationComponent } from './graph-rag-visualization.component';
import { GraphSceneService } from './graph-scene.service';

const API_URL = 'http://api.test/api/';
const VISUALIZATION_URL = `${API_URL}graph-rag/42/visualization/`;
const INITIAL_REQUEST_URL = `${VISUALIZATION_URL}?max_entities=200`;
const LINK_PAIRS_URL = `${API_URL}graph-rag/table-link-pairs/`;

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function buildVisualizationData(entityCount = 3, totalEntities = entityCount): GraphVisualizationData {
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
        total_entities: totalEntities,
        total_relationships: 1,
    };
}

/** What the backend sends when it cannot read the communities: every entity with empty `community_ids`. */
function withoutCommunities(data: GraphVisualizationData): GraphVisualizationData {
    return { ...data, entities: data.entities.map((entity) => ({ ...entity, community_ids: [] })) };
}

function emptyVisualizationData(): GraphVisualizationData {
    return { entities: [], relationships: [], total_entities: 0, total_relationships: 0 };
}

/**
 * WebGL is not available in the test DOM, so the scene service is replaced by a fake that keeps the
 * real graph bookkeeping but never creates a renderer. Loading the 3D libraries is held open until
 * the test resolves it, to exercise what happens when the component goes away mid-load.
 */
@Injectable()
class FakeGraphSceneService extends GraphSceneService {
    initSceneCalls = 0;
    refreshGraphCalls = 0;
    /** The node color mode the scene was last told to paint. */
    paintsByCommunity = false;
    private sceneInitialized = false;
    private resolveDependencies: () => void = () => {};
    private readonly dependencies = new Promise<void>((resolve) => (this.resolveDependencies = resolve));

    override loadDependencies(): Promise<void> {
        return this.dependencies;
    }

    finishLoadingDependencies(): void {
        this.resolveDependencies();
    }

    override initScene(): void {
        this.initSceneCalls++;
        this.sceneInitialized = true;
    }

    override isSceneInitialized(): boolean {
        return this.sceneInitialized;
    }

    override refreshGraph(): void {
        this.refreshGraphCalls++;
    }

    override setColorByCommunity(enabled: boolean): void {
        this.paintsByCommunity = enabled;
        super.setColorByCommunity(enabled);
    }

    override dispose(): void {
        this.sceneInitialized = false;
    }
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

    function getSceneService(): FakeGraphSceneService {
        return fixture.debugElement
            .query(By.directive(GraphRagVisualizationComponent))
            .injector.get(GraphSceneService) as FakeGraphSceneService;
    }

    function textContent(): string {
        return (fixture.nativeElement as HTMLElement).textContent ?? '';
    }

    function query(selector: string): HTMLElement | null {
        return (fixture.nativeElement as HTMLElement).querySelector(selector);
    }

    function normalizedText(selector: string): string {
        return (query(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();
    }

    function flushInitial(data: GraphVisualizationData = buildVisualizationData()): void {
        httpMock.expectOne(INITIAL_REQUEST_URL).flush(data);
        fixture.detectChanges();
    }

    /** Types into the toolbar search field; the component debounces, so the caller advances the fake timers. */
    function typeSearch(term: string): void {
        const input = query('.search__input') as HTMLInputElement;
        input.value = term;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    /** Types a number into the "Displayed Entities" field and leaves it, which commits the value. */
    function enterDisplayedEntities(value: string): void {
        const input = query('.visualization__slider .slider-stepper__value-input') as HTMLInputElement;
        input.value = value;
        input.dispatchEvent(new Event('blur'));
        fixture.detectChanges();
    }

    function expectVisualizationRequest(params: Record<string, string | null>) {
        return httpMock.expectOne(
            (request) =>
                request.url === VISUALIZATION_URL &&
                Object.entries(params).every(([key, value]) => request.params.get(key) === value)
        );
    }

    function typeFilterCheckboxes(): HTMLInputElement[] {
        return Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLInputElement>(
                '.visualization__sidebar input[type="checkbox"]'
            )
        );
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
        })
            .overrideComponent(GraphRagVisualizationComponent, {
                set: { providers: [{ provide: GraphSceneService, useClass: FakeGraphSceneService }] },
            })
            .compileComponents();

        // The link-pairs store caches per session; reset so each test starts with an empty cache.
        TestBed.inject(GraphRagLinkPairsStorageService).resetForTesting();

        fixture = TestBed.createComponent(TestHostComponent);
        httpMock = TestBed.inject(HttpTestingController);
        fixture.detectChanges();

        // The visualization primes the link-pairs cache on init; flush it so the tests only have
        // to reason about the visualization request itself.
        httpMock.expectOne(LINK_PAIRS_URL).flush({});
    });

    afterEach(() => {
        httpMock.verify();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    describe('loading', () => {
        it('requests 200 entities on init', () => {
            const request = httpMock.expectOne(INITIAL_REQUEST_URL);
            expect(request.request.method).toBe('GET');
            request.flush(buildVisualizationData());
        });

        it('shows a loading spinner while fetching', () => {
            expect(query('app-loading-spinner')).not.toBeNull();

            flushInitial();
        });

        it('says the graph has no entities when the first load is empty', () => {
            flushInitial(emptyVisualizationData());

            expect(textContent()).toContain('This graph has no entities to display');
            expect(textContent()).not.toContain('run indexing first');
            expect(query('app-loading-spinner')).toBeNull();
        });

        it('shows the total entity and relationship counts after a successful load', () => {
            flushInitial(buildVisualizationData(5));

            expect(normalizedText('.visualization__stats')).toBe('of 5/Relationships: 1');
        });

        it('builds entity type filters from loaded data', () => {
            flushInitial(buildVisualizationData(4));

            expect(textContent()).toContain('PERSON (2)');
            expect(textContent()).toContain('ORG (2)');
        });
    });

    describe('errors', () => {
        it('tells the user to run indexing when the graph is not indexed yet (409 graph_not_indexed)', () => {
            httpMock
                .expectOne(INITIAL_REQUEST_URL)
                .flush(
                    { status_code: 409, code: 'graph_not_indexed', message: 'Any backend wording' },
                    { status: 409, statusText: 'Conflict' }
                );
            fixture.detectChanges();

            expect(textContent()).toContain('run indexing first');
            expect(query('app-fetch-error-state')).toBeNull();
            expect(query('app-loading-spinner')).toBeNull();
        });

        it.each<[string, number, object]>([
            ['a 409 with another code', 409, { status_code: 409, code: 'upstream_resource_conflict', message: 'x' }],
            ['a 404', 404, { status_code: 404, code: 'not_found', message: 'GraphRag not found' }],
        ])('shows an error with retry, not the indexing hint, for %s', (_label, status, body) => {
            httpMock.expectOne(INITIAL_REQUEST_URL).flush(body, { status, statusText: 'Error' });
            fixture.detectChanges();

            expect(query('app-fetch-error-state')).not.toBeNull();
            expect(textContent()).not.toContain('run indexing first');
        });

        it('says GraphRAG is unavailable on a 503', () => {
            httpMock
                .expectOne(INITIAL_REQUEST_URL)
                .flush({ message: 'unavailable' }, { status: 503, statusText: 'Service Unavailable' });
            fixture.detectChanges();

            expect(query('app-fetch-error-state')).not.toBeNull();
            expect(textContent()).toContain('GraphRAG is not available on this server');
        });
    });

    describe('displayed entities', () => {
        it('lets the user ask for every entity when the first load returned only part of the graph', () => {
            flushInitial(buildVisualizationData(200, 5000));

            enterDisplayedEntities('5000');

            // 5000 exceeds GRAPH_VISUALIZATION_MAX_ENTITIES_PER_REQUEST (1000), so the service splits
            // the fetch into GRAPH_VISUALIZATION_MAX_PARALLEL_PAGES (5) parallel page requests.
            const pageCount = 5;
            for (let page = 0; page < pageCount; page++) {
                expectVisualizationRequest({
                    max_entities: '1000',
                    page: page.toString(),
                    page_count: pageCount.toString(),
                }).flush(buildVisualizationData(200, 5000));
            }
        });

        it('never requests fewer than one entity', () => {
            flushInitial();

            enterDisplayedEntities('0');

            expectVisualizationRequest({ max_entities: '1' }).flush(buildVisualizationData(1));
        });

        it('keeps the type filters on screen but disabled while a reload is in flight', () => {
            flushInitial(buildVisualizationData(4));
            expect(typeFilterCheckboxes().length).toBe(2);
            expect(typeFilterCheckboxes().every((checkbox) => !checkbox.disabled)).toBe(true);

            enterDisplayedEntities('2');

            expect(query('.visualization__sidebar')).not.toBeNull();
            expect(typeFilterCheckboxes().length).toBe(2);
            expect(typeFilterCheckboxes().every((checkbox) => checkbox.disabled)).toBe(true);

            expectVisualizationRequest({ max_entities: '2' }).flush(buildVisualizationData(2));
            fixture.detectChanges();

            expect(typeFilterCheckboxes().every((checkbox) => !checkbox.disabled)).toBe(true);
        });
    });

    describe('group by community', () => {
        function groupByCommunitySwitch(): HTMLInputElement {
            const control = Array.from(
                (fixture.nativeElement as HTMLElement).querySelectorAll('.visualization__toolbar-control')
            ).find((element) => element.textContent?.includes('Group by Community'));
            return control!.querySelector('input[type="checkbox"]') as HTMLInputElement;
        }

        function typeSwatchCount(): number {
            return (fixture.nativeElement as HTMLElement).querySelectorAll('.visualization__filter-color').length;
        }

        function groupByCommunityTooltip(): MatTooltip {
            return fixture.debugElement
                .queryAll(By.directive(MatTooltip))
                .map((element) => element.injector.get(MatTooltip))
                .find((tooltip) => tooltip.message === 'This graph has no communities to group by')!;
        }

        it('starts grouped by community, without type swatches, keeping the type filters usable', () => {
            flushInitial(buildVisualizationData(4));

            expect(groupByCommunitySwitch().checked).toBe(true);
            expect(getSceneService().paintsByCommunity).toBe(true);
            expect(typeSwatchCount()).toBe(0);
            expect(typeFilterCheckboxes().length).toBe(2);
            expect(typeFilterCheckboxes().every((checkbox) => !checkbox.disabled)).toBe(true);
        });

        it('names the switch for assistive technology', () => {
            flushInitial();

            expect(groupByCommunitySwitch().getAttribute('aria-label')).toBe('Group by community');
        });

        it('colors nodes by type with a swatch next to every entity type once ungrouped', () => {
            flushInitial(buildVisualizationData(4));

            groupByCommunitySwitch().click();
            fixture.detectChanges();

            expect(groupByCommunitySwitch().checked).toBe(false);
            expect(getSceneService().paintsByCommunity).toBe(false);
            expect(typeSwatchCount()).toBe(2);
        });

        it('returns to community colors without type swatches when grouped again', () => {
            flushInitial(buildVisualizationData(4));

            groupByCommunitySwitch().click();
            fixture.detectChanges();
            groupByCommunitySwitch().click();
            fixture.detectChanges();

            expect(groupByCommunitySwitch().checked).toBe(true);
            expect(getSceneService().paintsByCommunity).toBe(true);
            expect(typeSwatchCount()).toBe(0);
        });

        it('disables the switch and explains why when no entity has a community', () => {
            flushInitial(withoutCommunities(buildVisualizationData(4)));

            expect(groupByCommunitySwitch().disabled).toBe(true);
            expect(groupByCommunityTooltip().disabled).toBe(false);
        });

        it('offers the switch without the explanation when the graph has communities', () => {
            flushInitial(buildVisualizationData(4));

            expect(groupByCommunitySwitch().disabled).toBe(false);
            expect(groupByCommunityTooltip().disabled).toBe(true);
        });

        it('ungroups when a reload brings a graph without communities', () => {
            flushInitial(buildVisualizationData(4));
            groupByCommunitySwitch().click();
            fixture.detectChanges();

            enterDisplayedEntities('2');
            expectVisualizationRequest({ max_entities: '2' }).flush(withoutCommunities(buildVisualizationData(2)));
            fixture.detectChanges();

            expect(groupByCommunitySwitch().checked).toBe(false);
            expect(groupByCommunitySwitch().disabled).toBe(true);
            expect(getSceneService().paintsByCommunity).toBe(false);
            expect(typeSwatchCount()).toBe(2);
        });
    });

    describe('scene lifecycle', () => {
        async function initializeScene(): Promise<FakeGraphSceneService> {
            flushInitial();
            const sceneService = getSceneService();
            sceneService.finishLoadingDependencies();
            await fixture.whenStable();
            return sceneService;
        }

        it('creates the scene once the 3D libraries have loaded', async () => {
            const sceneService = await initializeScene();

            expect(sceneService.initSceneCalls).toBe(1);
        });

        it('does not create a scene when destroyed while the 3D libraries are still loading', async () => {
            flushInitial();
            const sceneService = getSceneService();

            fixture.destroy();
            sceneService.finishLoadingDependencies();
            await Promise.resolve();
            await Promise.resolve();

            expect(sceneService.initSceneCalls).toBe(0);
        });

        it('updates the existing scene in place when the displayed entities change', async () => {
            const sceneService = await initializeScene();
            const canvas = query('canvas');

            enterDisplayedEntities('2');
            expectVisualizationRequest({ max_entities: '2' }).flush(buildVisualizationData(2));
            fixture.detectChanges();

            expect(sceneService.initSceneCalls).toBe(1);
            expect(sceneService.refreshGraphCalls).toBe(1);
            expect(query('canvas')).toBe(canvas);
        });

        it('updates the existing scene in place when a search reloads the graph', async () => {
            const sceneService = await initializeScene();
            const canvas = query('canvas');
            vi.useFakeTimers();

            typeSearch('Entity');
            vi.advanceTimersByTime(300);
            expectVisualizationRequest({ search: 'Entity' }).flush(buildVisualizationData(2));
            fixture.detectChanges();

            expect(sceneService.initSceneCalls).toBe(1);
            expect(sceneService.refreshGraphCalls).toBe(1);
            expect(query('canvas')).toBe(canvas);
        });
    });

    describe('API-driven search', () => {
        beforeEach(() => vi.useFakeTimers());

        it('limits the search field to 200 characters', () => {
            flushInitial();

            expect(query('.search__input')?.getAttribute('maxlength')).toBe('200');
        });

        it('sends the trimmed term with the displayed entity count after the debounce', () => {
            flushInitial();

            typeSearch('  test query  ');
            vi.advanceTimersByTime(300);

            const searchRequest = expectVisualizationRequest({ search: 'test query', max_entities: '3' });
            expect(searchRequest.request.method).toBe('GET');
            searchRequest.flush(buildVisualizationData(2));
        });

        it('keeps the toolbar and shows a no-results message when the search matches nothing', () => {
            flushInitial();

            typeSearch('nothing like this');
            vi.advanceTimersByTime(300);
            expectVisualizationRequest({ search: 'nothing like this' }).flush(emptyVisualizationData());
            fixture.detectChanges();

            expect(textContent()).toContain('No entities match your search');
            expect(query('app-loading-spinner')).toBeNull();
            expect(query('app-search')).not.toBeNull();
            expect(query('app-slider-with-stepper')).not.toBeNull();
        });

        it('reloads without a search param when the term is reduced to whitespace', () => {
            flushInitial();
            typeSearch('abc');
            vi.advanceTimersByTime(300);
            expectVisualizationRequest({ search: 'abc' }).flush(buildVisualizationData());

            typeSearch('   ');
            vi.advanceTimersByTime(300);

            const reloadRequest = httpMock.expectOne((request) => request.url === VISUALIZATION_URL);
            expect(reloadRequest.request.params.has('search')).toBe(false);
            reloadRequest.flush(buildVisualizationData());
        });

        it('debounces rapid search input', () => {
            flushInitial();

            typeSearch('a');
            vi.advanceTimersByTime(100);
            typeSearch('ab');
            vi.advanceTimersByTime(100);
            typeSearch('abc');
            vi.advanceTimersByTime(300);

            // Only the last value triggers a request
            expectVisualizationRequest({ search: 'abc' }).flush(buildVisualizationData(1));
        });

        it('does not search again when the debounced term is the one already searched', () => {
            flushInitial();
            typeSearch('same');
            vi.advanceTimersByTime(300);
            expectVisualizationRequest({ search: 'same' }).flush(buildVisualizationData(2));

            // Edited and changed back within the debounce window: the settled term is unchanged.
            typeSearch('samex');
            vi.advanceTimersByTime(100);
            typeSearch('same');
            vi.advanceTimersByTime(300);

            httpMock.expectNone((request) => request.url === VISUALIZATION_URL);
        });

        it('rebuilds entity type filters from the search result', () => {
            flushInitial(buildVisualizationData(4));
            expect(textContent()).toContain('ORG (2)');

            typeSearch('person');
            vi.advanceTimersByTime(300);
            expectVisualizationRequest({ search: 'person' }).flush(buildVisualizationData(1));
            fixture.detectChanges();

            expect(textContent()).toContain('PERSON (1)');
            expect(textContent()).not.toContain('ORG (');
        });

        it('keeps the search term when the displayed entities change during a search', () => {
            flushInitial();
            typeSearch('query');
            vi.advanceTimersByTime(300);
            expectVisualizationRequest({ search: 'query' }).flush(buildVisualizationData(2));
            fixture.detectChanges();

            enterDisplayedEntities('2');

            expectVisualizationRequest({ max_entities: '2', search: 'query' }).flush(buildVisualizationData(2));
        });
    });
});
