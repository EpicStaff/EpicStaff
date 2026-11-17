import { Dialog } from '@angular/cdk/dialog';
import { Location } from '@angular/common';
import { Component, NO_ERRORS_SCHEMA, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { Observable, of, Subject } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { NaiveRagConfigurationDialog } from '../../components/rag-configuration-dialog/naive-rag-configuration-dialog/naive-rag-configuration-dialog.component';
import { ChunkDeepLinkParams, ChunkDeepLinkService } from '../../services/chunk-deep-link.service';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { CollectionsListPageComponent } from './collections-list-page.component';

const COLLECTION_ID = 4;
const NAIVE_RAG_ID = 7;
const GRAPH_RAG_ID = 8;

/** Hosts the page the way the Storage page does: not routed itself, under the `storage` route with a component-less tab. */
@Component({ template: '<app-collections-list-page />', imports: [CollectionsListPageComponent] })
class StorageHostComponent {}

describe('CollectionsListPageComponent ?collection= deep link', () => {
    async function openAt(
        url: string,
        {
            chunkLink = null,
            collectionsLoad = of([]),
        }: { chunkLink?: ChunkDeepLinkParams | null; collectionsLoad?: Observable<unknown> } = {}
    ): Promise<{
        selectedCollectionId: () => number | null;
        openDialog: ReturnType<typeof vi.fn>;
        router: Router;
        harness: RouterTestingHarness;
    }> {
        const selectedCollectionId = signal<number | null>(null);
        const openDialog = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    {
                        path: 'storage',
                        component: StorageHostComponent,
                        children: [{ path: 'knowledge-sources', children: [] }],
                    },
                    { path: 'other', children: [] },
                ]),
                {
                    provide: CollectionsStorageService,
                    useValue: {
                        collections: signal([{ collection_id: COLLECTION_ID }]),
                        getCollections: () => collectionsLoad,
                        setSelectedCollectionId: (id: number | null) => selectedCollectionId.set(id),
                        getFullCollection: () =>
                            of({
                                collection_id: COLLECTION_ID,
                                rag_configurations: [
                                    { rag_id: NAIVE_RAG_ID, rag_type: 'naive' },
                                    { rag_id: GRAPH_RAG_ID, rag_type: 'graph' },
                                ],
                            }),
                    },
                },
                {
                    provide: KnowledgeSourcesPollingService,
                    useValue: { startPagePolling: () => undefined, stopPagePolling: () => undefined },
                },
                // The chunk link reads `window.location`, which a test cannot set: a fake says whether one is pending.
                {
                    provide: ChunkDeepLinkService,
                    useValue: {
                        initFromUrl: () => undefined,
                        pending: signal(chunkLink),
                        consume: () => null,
                        clearUrl: () => undefined,
                    },
                },
                { provide: Dialog, useValue: { open: openDialog } },
                { provide: ToastService, useValue: { error: vi.fn() } },
            ],
        });
        // Only the deep link is under test: the sidebar and details panes stay unrendered elements.
        TestBed.overrideComponent(CollectionsListPageComponent, {
            set: { imports: [], schemas: [NO_ERRORS_SCHEMA] },
        });
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl(url);
        await harness.fixture.whenStable();
        return { selectedCollectionId, openDialog, router: TestBed.inject(Router), harness };
    }

    it('selects the collection without opening a RAG, and drops the param from the URL', async () => {
        const { selectedCollectionId, openDialog, router } = await openAt(
            `/storage/knowledge-sources?collection=${COLLECTION_ID}#files`
        );

        expect(selectedCollectionId()).toBe(COLLECTION_ID);
        expect(openDialog).not.toHaveBeenCalled();
        expect(router.url).toBe('/storage/knowledge-sources#files');
    });

    it('keeps the history state the link was opened with when it drops the param', async () => {
        const { harness } = await openAt('/other');

        await TestBed.inject(Router).navigateByUrl(`/storage/knowledge-sources?collection=${COLLECTION_ID}`, {
            state: { from: 'audit' },
        });
        harness.detectChanges();
        await harness.fixture.whenStable();

        expect(TestBed.inject(Location).path()).toBe('/storage/knowledge-sources');
        expect(TestBed.inject(Location).getState()).toEqual(expect.objectContaining({ from: 'audit' }));
    });

    it('with &rag= also opens that naive RAG configuration', async () => {
        const { selectedCollectionId, openDialog } = await openAt(
            `/storage/knowledge-sources?collection=${COLLECTION_ID}&rag=${NAIVE_RAG_ID}`
        );

        expect(selectedCollectionId()).toBe(COLLECTION_ID);
        expect(openDialog).toHaveBeenCalledExactlyOnceWith(
            NaiveRagConfigurationDialog,
            expect.objectContaining({
                data: { ragId: NAIVE_RAG_ID, ragType: 'naive', collectionId: COLLECTION_ID },
            })
        );
    });

    it.each([
        ['an unknown collection', `?collection=999&rag=${NAIVE_RAG_ID}`, null],
        [
            'a RAG id that is not a naive RAG of the collection',
            `?collection=${COLLECTION_ID}&rag=${GRAPH_RAG_ID}`,
            COLLECTION_ID,
        ],
    ])('opens nothing for %s', async (_case, query, expectedSelection) => {
        const { selectedCollectionId, openDialog } = await openAt(`/storage/knowledge-sources${query}`);

        expect(selectedCollectionId()).toBe(expectedSelection);
        expect(openDialog).not.toHaveBeenCalled();
    });

    it('leaves a four-param chunk link to itself: one dialog, and its params stay in the URL', async () => {
        const url = `/storage/knowledge-sources?collection=${COLLECTION_ID}&rag=${NAIVE_RAG_ID}&doc=5&chunk=6`;
        const { openDialog, router } = await openAt(url, {
            chunkLink: { collectionId: COLLECTION_ID, ragId: NAIVE_RAG_ID, documentId: 5, chunkId: 6 },
        });

        expect(openDialog).toHaveBeenCalledOnce();
        expect(router.url).toBe(url);
    });

    it('follows nothing when the page is left before its list loads', async () => {
        const { selectedCollectionId, openDialog, router, harness } = await openAt(
            `/storage/knowledge-sources?collection=${COLLECTION_ID}&rag=${NAIVE_RAG_ID}`,
            { collectionsLoad: new Subject() }
        );

        await harness.navigateByUrl('/other');
        await harness.fixture.whenStable();

        expect(router.url).toBe('/other');
        expect(selectedCollectionId()).toBeNull();
        expect(openDialog).not.toHaveBeenCalled();
    });
});
