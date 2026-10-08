// Side-effect import: the real tab pages' dependency graph reaches shared/utils/http-error.util.ts,
// which reads the `validationErrors` augmentation declared by this interceptor module.
import '../../../../core/interceptors/validation-errors.interceptor';

import { Dialog } from '@angular/cdk/dialog';
import { Component, inject, OnDestroy } from '@angular/core';
import { ComponentFixture, DeferBlockBehavior, DeferBlockState, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { KeyValueTablesPageComponent } from '../../../key-value-tables/pages/key-value-tables-page/key-value-tables-page.component';
import { CollectionsListPageComponent } from '../../../knowledge-sources/pages/collections-list-page/collections-list-page.component';
import { CollectionsStorageService } from '../../../knowledge-sources/services/collections-storage.service';
import { StorageItem } from '../../models/storage.models';
import { FilesSearchService } from '../../services/files-search.service';
import { StorageApiService } from '../../services/storage-api.service';
import { StorageDragService } from '../../services/storage-drag.service';
import { StoragePageComponent } from './components/storage-page/storage-page.component';
import { FilesListPageComponent, TAB_SPRING_LOAD_DELAY_MS } from './files-list-page.component';

const lifecycle = { storageCreated: 0, storageDestroyed: 0, deepLinkPath: null as string | null };

/** Reads `?path=` exactly like the real StoragePageComponent (its injected ActivatedRoute, on construction). */
@Component({ selector: 'app-storage-page', template: '<div class="storage-stub">storage</div>' })
class StoragePageStubComponent implements OnDestroy {
    constructor() {
        lifecycle.storageCreated++;
        lifecycle.deepLinkPath = inject(ActivatedRoute).snapshot.queryParamMap.get('path');
    }

    ngOnDestroy(): void {
        lifecycle.storageDestroyed++;
    }
}

@Component({ selector: 'app-collections-list-page', template: '<div class="collections-stub">collections</div>' })
class CollectionsListPageStubComponent {}

@Component({ selector: 'app-key-value-tables-page', template: '<div class="key-value-tables-stub">kv</div>' })
class KeyValueTablesPageStubComponent {}

const file: StorageItem = { id: 1, name: 'a.pdf', path: 'a.pdf', type: 'file' };

describe('FilesListPageComponent', () => {
    let harness: RouterTestingHarness;
    let storageDrag: StorageDragService;
    let canReadKnowledge: boolean;
    let canAll: boolean;

    function fixture(): ComponentFixture<unknown> {
        return harness.fixture;
    }

    function query(selector: string): HTMLElement | null {
        return (fixture().nativeElement as HTMLElement).querySelector(selector);
    }

    function storageLayer(): HTMLElement | null {
        return query('.storage-stub')?.closest('.tab-page') ?? null;
    }

    async function settle(): Promise<void> {
        fixture().detectChanges();
        await fixture().whenStable();
        fixture().detectChanges();
    }

    /**
     * The lazy loading of the tab pages is Angular's @defer (with a real-time `@loading` minimum);
     * what this spec covers is the @if inside each block, so the blocks are loaded up front.
     */
    let deferBlocksLoaded = false;
    async function loadDeferBlocks(state = DeferBlockState.Complete): Promise<void> {
        for (const block of await fixture().getDeferBlocks()) await block.render(state);
        deferBlocksLoaded = true;
    }

    async function navigate(url: string): Promise<void> {
        await harness.navigateByUrl(url);
        if (!deferBlocksLoaded) await loadDeferBlocks();
        await settle();
    }

    beforeEach(async () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        deferBlocksLoaded = false;
        lifecycle.storageCreated = 0;
        lifecycle.storageDestroyed = 0;
        lifecycle.deepLinkPath = null;
        canReadKnowledge = true;
        canAll = true;
        // jsdom has no ResizeObserver; the header's overflow directives need one.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );

        TestBed.configureTestingModule({
            deferBlockBehavior: DeferBlockBehavior.Manual,
            providers: [
                provideRouter([
                    {
                        path: 'storage',
                        component: FilesListPageComponent,
                        children: [
                            {
                                path: 'knowledge-sources',
                                canActivate: [() => canReadKnowledge],
                                children: [],
                            },
                            { path: 'files', children: [] },
                            { path: 'key-value-tables', children: [] },
                        ],
                    },
                ]),
                { provide: Dialog, useValue: { open: vi.fn() } },
                { provide: StorageApiService, useValue: { triggerRefresh: vi.fn() } },
                { provide: CollectionsStorageService, useValue: {} },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
                {
                    provide: PermissionsService,
                    useValue: { can: () => canAll },
                },
            ],
        });
        TestBed.overrideComponent(FilesListPageComponent, {
            remove: { imports: [CollectionsListPageComponent, StoragePageComponent, KeyValueTablesPageComponent] },
            add: {
                imports: [CollectionsListPageStubComponent, StoragePageStubComponent, KeyValueTablesPageStubComponent],
            },
        });
        await TestBed.compileComponents();
        storageDrag = TestBed.inject(StorageDragService);
        harness = await RouterTestingHarness.create();
    });

    afterEach(() => {
        storageDrag?.end();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it('renders only the Storage page on the storage tab, visibly', async () => {
        await navigate('/storage/files');

        expect(query('.storage-stub')).not.toBeNull();
        expect(query('.collections-stub')).toBeNull();
        expect(storageLayer()?.classList).not.toContain('tab-page--kept-alive');
        expect(storageLayer()?.hasAttribute('inert')).toBe(false);
        expect(query('app-button')?.textContent).toContain('Add files');
    });

    it('renders only the Knowledge Sources page on its tab', async () => {
        await navigate('/storage/knowledge-sources');

        expect(query('.collections-stub')).not.toBeNull();
        expect(query('.storage-stub')).toBeNull();
        expect(query('app-button')?.textContent).toContain('Add collection');
    });

    it('shows a spinner while a tab page is still loading', async () => {
        await harness.navigateByUrl('/storage/files');
        await loadDeferBlocks(DeferBlockState.Loading);
        fixture().detectChanges();

        expect(query('.tab-page__loading app-spinner')?.textContent).toContain('Loading');
        expect(query('.storage-stub')).toBeNull();
    });

    it('unmounts the Storage page on a plain tab switch', async () => {
        await navigate('/storage/files');
        await navigate('/storage/knowledge-sources');

        expect(query('.storage-stub')).toBeNull();
        expect(lifecycle.storageDestroyed).toBe(1);
    });

    it('keeps the same Storage page mounted, hidden but rendered, while a drag from it is live', async () => {
        await navigate('/storage/files');
        const storageElement = query('.storage-stub');
        storageDrag.start(file);

        await navigate('/storage/knowledge-sources');

        expect(query('.collections-stub')).not.toBeNull();
        expect(query('.storage-stub')).toBe(storageElement);
        expect(lifecycle.storageCreated).toBe(1);
        expect(lifecycle.storageDestroyed).toBe(0);
        const layer = storageLayer() as HTMLElement;
        expect(layer.classList).toContain('tab-page--kept-alive');
        expect(layer.hasAttribute('inert')).toBe(true);
        expect(layer.hidden).toBe(false);
        expect(layer.style.display).not.toBe('none');
    });

    it('unmounts the kept-alive Storage page once the drag ends', async () => {
        await navigate('/storage/files');
        storageDrag.start(file);
        await navigate('/storage/knowledge-sources');

        storageDrag.end();
        await settle();

        expect(query('.storage-stub')).toBeNull();
        expect(lifecycle.storageDestroyed).toBe(1);
        expect(query('.collections-stub')).not.toBeNull();
    });

    it('shows the kept-alive Storage page again when the drag returns to its tab', async () => {
        await navigate('/storage/files');
        const storageElement = query('.storage-stub');
        storageDrag.start(file);
        await navigate('/storage/knowledge-sources');

        await navigate('/storage/files');

        expect(query('.storage-stub')).toBe(storageElement);
        expect(storageLayer()?.classList).not.toContain('tab-page--kept-alive');
        expect(storageLayer()?.hasAttribute('inert')).toBe(false);
        expect(query('.collections-stub')).toBeNull();
    });

    it('never mounts the Storage page just because a drag is live elsewhere', async () => {
        await navigate('/storage/knowledge-sources');

        storageDrag.start(file);
        await settle();

        expect(query('.storage-stub')).toBeNull();
        expect(lifecycle.storageCreated).toBe(0);
    });

    it('renders only the Key-Value Tables page on its tab, with no header create button', async () => {
        await navigate('/storage/key-value-tables');

        expect(query('.key-value-tables-stub')).not.toBeNull();
        expect(query('.storage-stub')).toBeNull();
        expect(query('.collections-stub')).toBeNull();
        // Positive control for the button is the storage-tab test above (same permissions).
        expect(query('.header-actions app-button')).toBeNull();
    });

    describe('header search', () => {
        function headerSearch(): HTMLInputElement | null {
            return query('.search-input') as HTMLInputElement | null;
        }

        it('is gone on Key-Value Tables, which searches keys in its own grid, and back on another tab', async () => {
            await navigate('/storage/key-value-tables');
            expect(headerSearch()).toBeNull();

            await navigate('/storage/files');
            expect(headerSearch()?.placeholder).toBe('Search collections, folders, files...');

            // The tab comes from the route, not from a folder named like another tab in the query.
            await navigate('/storage/files?path=/key-value-tables');
            expect(headerSearch()?.placeholder).toBe('Search collections, folders, files...');
        });

        it('clears the search term when the tab changes, not within the same tab', async () => {
            await navigate('/storage/files');
            const search = harness.routeDebugElement!.injector.get(FilesSearchService);

            search.setSearchTerm('report');
            await navigate('/storage/files?page=2');
            expect(search.searchTerm()).toBe('report');

            await navigate('/storage/key-value-tables');
            expect(search.searchTerm()).toBe('');
        });

        it('hides the header create button when the user lacks the permission', async () => {
            canAll = false;
            await navigate('/storage/files');

            expect(query('.header-actions app-button')).toBeNull();
        });
    });

    describe('storage deep link (?path=), e.g. from the export-session-files dialog', () => {
        it('is readable by the Storage page through its injected ActivatedRoute', async () => {
            await navigate('/storage/files?path=a/b');

            expect(lifecycle.deepLinkPath).toBe('a/b');
        });

        it('is readable when arriving from the Knowledge Sources tab', async () => {
            await navigate('/storage/knowledge-sources');

            await navigate('/storage/files?path=reports/q1.pdf');

            expect(lifecycle.deepLinkPath).toBe('reports/q1.pdf');
        });
    });

    describe('spring-loaded tabs', () => {
        async function waitForSpringLoad(): Promise<void> {
            await vi.advanceTimersByTimeAsync(TAB_SPRING_LOAD_DELAY_MS);
            await settle();
        }

        function tab(link: string): HTMLElement {
            return query(`app-tab-button[data-tab="${link}"]`) as HTMLElement;
        }

        async function restOnTab(link: string): Promise<void> {
            tab(link).dispatchEvent(new Event('dragenter', { bubbles: true }));
            fixture().detectChanges();
            await waitForSpringLoad();
        }

        it('opens Knowledge Sources when a storage drag rests on its tab', async () => {
            await navigate('/storage/files');
            storageDrag.start(file);
            await settle();

            tab('knowledge-sources').dispatchEvent(new Event('dragenter', { bubbles: true }));
            fixture().detectChanges();
            expect(tab('knowledge-sources').classList).toContain('tab-spring-loading');
            await vi.advanceTimersByTimeAsync(TAB_SPRING_LOAD_DELAY_MS - 1);
            expect(TestBed.inject(Router).url).toBe('/storage/files');
            await waitForSpringLoad();

            expect(TestBed.inject(Router).url).toBe('/storage/knowledge-sources');
            expect(query('.collections-stub')).not.toBeNull();
            expect(storageLayer()?.classList).toContain('tab-page--kept-alive');
        });

        it('ignores drags that are not storage drags (e.g. OS files)', async () => {
            await navigate('/storage/files');

            await restOnTab('knowledge-sources');

            expect(TestBed.inject(Router).url).toBe('/storage/files');
            expect(tab('knowledge-sources').classList).not.toContain('tab-spring-loading');
        });

        it('cancels when the drag leaves the tab before the delay', async () => {
            await navigate('/storage/files');
            storageDrag.start(file);
            await settle();

            tab('knowledge-sources').dispatchEvent(new Event('dragenter', { bubbles: true }));
            tab('knowledge-sources').dispatchEvent(
                Object.assign(new Event('dragleave', { bubbles: true }), { relatedTarget: document.body })
            );
            await waitForSpringLoad();

            expect(TestBed.inject(Router).url).toBe('/storage/files');
        });

        it('does not navigate to a tab the guard refuses', async () => {
            await navigate('/storage/files');
            storageDrag.start(file);
            canReadKnowledge = false;
            await settle();

            await restOnTab('knowledge-sources');

            expect(TestBed.inject(Router).url).toBe('/storage/files');
            expect(query('.storage-stub')).not.toBeNull();
        });
    });
});
