import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { FetchErrorStateComponent, SpinnerComponent } from '@shared/components';
import { STORAGE_SIDEBAR_WIDTH_KEY } from '@shared/constants';
import { ResizableSidebarDirective } from '@shared/directives';
import { SidebarWidthService } from '@shared/services';
import { takeQueryParams } from '@shared/utils';
import { finalize, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { CreateCollectionDialogComponent } from '../../components/create-collection-dialog/create-collection-dialog.component';
import { NaiveRagConfigurationDialog } from '../../components/rag-configuration-dialog/naive-rag-configuration-dialog/naive-rag-configuration-dialog.component';
import { ChunkDeepLinkService } from '../../services/chunk-deep-link.service';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { CollectionDetailsComponent } from './components/collection-details/collection-details.component';
import { CollectionsListItemSidebarComponent } from './components/collections-list-sidebar/collections-list-sidebar.component';

@Component({
    selector: 'app-collections-list-page',
    templateUrl: './collections-list-page.component.html',
    styleUrls: ['./collections-list-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        CollectionDetailsComponent,
        CollectionsListItemSidebarComponent,
        SpinnerComponent,
        FetchErrorStateComponent,
        ResizableSidebarDirective,
    ],
})
export class CollectionsListPageComponent implements OnInit, OnDestroy {
    private destroyRef = inject(DestroyRef);
    private dialog = inject(Dialog);
    private collectionsStorageService = inject(CollectionsStorageService);
    private pollingService = inject(KnowledgeSourcesPollingService);
    private deepLinkService = inject(ChunkDeepLinkService);
    private toastService = inject(ToastService);
    private readonly route = inject(ActivatedRoute);
    private readonly router = inject(Router);
    // A chunk link (all four params) opens its own way; otherwise `?collection=` is applied once, after the first load.
    private collectionLinkPending = false;

    isLoading = signal<boolean>(true);
    error = signal<string | null>(null);
    collections = this.collectionsStorageService.collections;

    protected readonly sidebarStorageKey = STORAGE_SIDEBAR_WIDTH_KEY;
    protected readonly sidebarWidth = inject(SidebarWidthService).getWidth(STORAGE_SIDEBAR_WIDTH_KEY);

    ngOnInit(): void {
        this.deepLinkService.initFromUrl();
        this.collectionLinkPending = this.deepLinkService.pending() === null;
        this.getCollections();
        this.pollingService.startPagePolling();
    }

    ngOnDestroy(): void {
        this.pollingService.stopPagePolling();
    }

    getCollections(): void {
        this.isLoading.set(true);
        this.error.set(null);

        this.collectionsStorageService
            .getCollections(true)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                // Links are followed only once the list has loaded: never after a failed load, nor after the page was
                // left mid-load (when `finalize` still runs).
                next: () => {
                    this.handleDeepLink();
                    this.applyCollectionLink();
                },
                error: () => this.error.set('Failed to load knowledge sources.'),
            });
    }

    retryLoad(): void {
        this.getCollections();
    }

    private handleDeepLink(): void {
        const params = this.deepLinkService.pending();
        if (!params) return;

        const collection = this.collections().find((c) => c.collection_id === params.collectionId);
        if (!collection) {
            this.toastService.error('Deep link: collection not found');
            this.deepLinkService.consume();
            this.deepLinkService.clearUrl();
            return;
        }

        this.collectionsStorageService.setSelectedCollectionId(params.collectionId);

        this.collectionsStorageService
            .getFullCollection(params.collectionId, true)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (fullCollection) => {
                    if (!fullCollection) {
                        this.toastService.error('Deep link: collection data not found');
                        this.deepLinkService.consume();
                        this.deepLinkService.clearUrl();
                        return;
                    }

                    // Chunk deep links only ever point at naive RAG documents (see
                    // ChunkDeepLinkService) — scope the match to 'naive' explicitly, since
                    // naive and graph rag_id sequences are independent and can collide.
                    const ragConfig = fullCollection.rag_configurations.find(
                        (r) => r.rag_id === params.ragId && r.rag_type === 'naive'
                    );
                    if (!ragConfig) {
                        this.toastService.error('Deep link: RAG configuration not found');
                        this.deepLinkService.consume();
                        this.deepLinkService.clearUrl();
                        return;
                    }

                    this.openDeepLinkDialog(params.collectionId, params.ragId);
                },
                error: () => {
                    this.toastService.error('Deep link: failed to load collection');
                    this.deepLinkService.consume();
                    this.deepLinkService.clearUrl();
                },
            });
    }

    /** `?collection=` selects that collection; `&rag=` also opens that naive RAG's configuration. Unknown ids are ignored. */
    private applyCollectionLink(): void {
        if (!this.collectionLinkPending) return;
        this.collectionLinkPending = false;
        const { collection, rag } = takeQueryParams(this.route, this.router, ['collection', 'rag']);
        const collectionId = Number(collection);
        if (!this.collections().some((candidate) => candidate.collection_id === collectionId)) return;
        this.collectionsStorageService.setSelectedCollectionId(collectionId);
        if (rag == null) return;
        const ragId = Number(rag);
        this.collectionsStorageService
            .getFullCollection(collectionId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (fullCollection) => {
                    // Naive and graph RAG ids are separate sequences: only a naive RAG of this collection opens.
                    const isNaiveRag = fullCollection?.rag_configurations.some(
                        (config) => config.rag_id === ragId && config.rag_type === 'naive'
                    );
                    if (isNaiveRag) this.openDeepLinkDialog(collectionId, ragId);
                },
                // The collection stays selected; its own pane reports a failed load.
                error: () => undefined,
            });
    }

    private openDeepLinkDialog(collectionId: number, ragId: number): void {
        this.dialog.open(NaiveRagConfigurationDialog, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { ragId, ragType: 'naive', collectionId },
            disableClose: true,
        });
    }

    createCollection(): void {
        this.collectionsStorageService
            .createCollection()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ collection_id }) => {
                    if (!collection_id) return;
                    this.collectionsStorageService.setSelectedCollectionId(collection_id);
                    this.openCreateModal(collection_id);
                },
                error: () => this.toastService.error('Failed to create collection'),
            });
    }

    private openCreateModal(collection_id: number): void {
        const dialog = this.dialog.open(CreateCollectionDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { collection_id },
            disableClose: true,
        });

        // Update collection info after modal closed
        dialog.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => {
                    return this.collectionsStorageService.getFullCollection(collection_id, true);
                })
            )
            .subscribe({
                next: () => {
                    this.collectionsStorageService.setSelectedCollectionId(collection_id);
                },
                error: () => {
                    this.toastService.error('Failed to get collection data');
                },
            });
    }
}
