import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications/toast.service';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { CreateCollectionDialogComponent } from '../../components/create-collection-dialog/create-collection-dialog.component';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { CollectionDetailsComponent } from './components/collection-details/collection-details.component';
import { CollectionsListItemSidebarComponent } from './components/collections-list-sidebar/collections-list-sidebar.component';

@Component({
    selector: 'app-collections-list-page',
    templateUrl: './collections-list-page.component.html',
    styleUrls: ['./collections-list-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [CollectionDetailsComponent, CollectionsListItemSidebarComponent, SpinnerComponent],
})
export class CollectionsListPageComponent implements OnInit {
    private destroyRef = inject(DestroyRef);
    private dialog = inject(Dialog);
    private collectionsStorageService = inject(CollectionsStorageService);
    private toastService = inject(ToastService);

    isLoading = signal<boolean>(true);
    collections = this.collectionsStorageService.collections;
    selectedCollectionId = signal<number | null>(null);

    ngOnInit(): void {
        this.getCollections();
    }

    getCollections(): void {
        this.isLoading.set(true);

        this.collectionsStorageService
            .getCollections()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                error: () => this.toastService.error('Failed to get collections.'),
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
        const dialog = this.dialog.open(CreateCollectionDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: collection_id,
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
