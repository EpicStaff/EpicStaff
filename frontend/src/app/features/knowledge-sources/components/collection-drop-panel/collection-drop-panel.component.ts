import { Component, computed, DestroyRef, effect, inject, input, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent } from '@shared/components';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { canImportStorageToKnowledge, isLikelyUnsupportedDocument } from '../../helpers/storage-import.util';
import { StorageImportCandidate } from '../../models/document.model';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { DocumentsStorageService } from '../../services/documents-storage.service';

/**
 * Native HTML5 drop targets — one per knowledge collection — for storage items being dragged.
 * The import itself runs in the root `DocumentsStorageService`, so it survives this panel.
 */
@Component({
    selector: 'app-collection-drop-panel',
    imports: [AppSvgIconComponent],
    templateUrl: './collection-drop-panel.component.html',
    styleUrls: ['./collection-drop-panel.component.scss'],
})
export class CollectionDropPanelComponent {
    readonly active = input<boolean>(false);
    readonly items = input<StorageImportCandidate[]>([]);

    protected readonly hoveredCollectionId = signal<number | null>(null);
    protected readonly loadFailed = signal<boolean>(false);
    protected readonly isVisible = computed(
        () => this.active() && canImportStorageToKnowledge(this.permissionsService)
    );
    protected readonly isLoading = computed(() => !this.collectionsStorage.isCollectionsLoaded() && !this.loadFailed());
    protected readonly itemsLabel = computed(() => {
        const items = this.items();
        return items.length === 1 ? `"${items[0].name}"` : `${items.length} items`;
    });
    protected readonly likelySkippedCount = computed(() => this.items().filter(isLikelyUnsupportedDocument).length);

    /** Loads collections the first time the panel becomes visible; a failed load is retried next time. */
    private readonly loadCollectionsOnFirstShow = effect(() => {
        if (!this.isVisible()) return;
        untracked(() => this.loadCollections());
    });

    protected readonly collectionsStorage = inject(CollectionsStorageService);
    protected readonly documentsStorage = inject(DocumentsStorageService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly destroyRef = inject(DestroyRef);
    private isLoadRequested = false;

    /** Swallows the drag everywhere on the panel except the collection rows. */
    onPanelDragOver(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
    }

    onPanelDrop(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();
    }

    onCollectionDragOver(event: DragEvent, collectionId: number): void {
        event.preventDefault();
        event.stopPropagation();
        const isBusy = this.documentsStorage.isImporting(collectionId);
        if (event.dataTransfer) event.dataTransfer.dropEffect = isBusy ? 'none' : 'copy';
        this.hoveredCollectionId.set(isBusy ? null : collectionId);
    }

    onCollectionDragLeave(event: DragEvent, collectionId: number): void {
        const row = event.currentTarget as HTMLElement | null;
        const related = event.relatedTarget as Node | null;
        if (row && related && row.contains(related)) return;
        if (this.hoveredCollectionId() === collectionId) {
            this.hoveredCollectionId.set(null);
        }
    }

    onCollectionDrop(event: DragEvent, collectionId: number): void {
        event.preventDefault();
        event.stopPropagation();
        this.hoveredCollectionId.set(null);
        if (!this.isVisible() || this.documentsStorage.isImporting(collectionId)) return;
        // Fire and forget: the service owns the request and the toasts.
        this.documentsStorage.importFromStorage(collectionId, this.items());
    }

    private loadCollections(): void {
        if (this.isLoadRequested || this.collectionsStorage.isCollectionsLoaded()) return;
        this.isLoadRequested = true;
        this.loadFailed.set(false);
        this.collectionsStorage
            .getCollections()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: () => {
                    this.isLoadRequested = false;
                    this.loadFailed.set(true);
                },
            });
    }
}
