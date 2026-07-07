import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications/toast.service';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
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
    imports: [CollectionDetailsComponent, CollectionsListItemSidebarComponent, SpinnerComponent],
})
export class CollectionsListPageComponent implements OnInit, OnDestroy {
    private destroyRef = inject(DestroyRef);
    private dialog = inject(Dialog);
    private collectionsStorageService = inject(CollectionsStorageService);
    private pollingService = inject(KnowledgeSourcesPollingService);
    private deepLinkService = inject(ChunkDeepLinkService);
    private toastService = inject(ToastService);

    isLoading = signal<boolean>(true);
    collections = this.collectionsStorageService.collections;
    selectedCollectionId = signal<number | null>(null);

    ngOnInit(): void {
        this.deepLinkService.initFromUrl();
        this.getCollections();
        this.pollingService.startPagePolling(this.selectedCollectionId);
    }

    ngOnDestroy(): void {
        this.pollingService.stopPagePolling();
    }

    getCollections(): void {
        this.isLoading.set(true);

        this.collectionsStorageService
            .getCollections(true)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => {
                    this.isLoading.set(false);
                    this.handleDeepLink();
                })
            )
            .subscribe({
                error: () => this.toastService.error('Failed to get collections.'),
            });
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

        this.selectedCollectionId.set(params.collectionId);

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

                    const ragConfig = fullCollection.rag_configurations.find((r) => r.rag_id === params.ragId);
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

    private openDeepLinkDialog(collectionId: number, ragId: number): void {
        this.dialog.open(NaiveRagConfigurationDialog, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { ragId, collectionId },
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
                    this.openCreateModal(collection_id);
                },
                error: () => this.toastService.error('Failed to create collection'),
            });
    }

    private openCreateModal(collection_id: number): void {
        this.selectedCollectionId.set(collection_id);

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
                    this.selectedCollectionId.set(collection_id);
                },
                error: () => {
                    this.toastService.error('Failed to get collection data');
                },
            });
    }
}
