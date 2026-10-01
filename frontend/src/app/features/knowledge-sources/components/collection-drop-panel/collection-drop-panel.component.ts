import { Component, computed, DestroyRef, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent } from '@shared/components';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { StorageDragService } from '../../../files/services/storage-drag.service';
import { CollectionDropTargetDirective } from '../../directives/collection-drop-target.directive';
import { canImportStorageToKnowledge, isLikelyUnsupportedDocument } from '../../helpers/storage-import.util';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { DocumentsStorageService } from '../../services/documents-storage.service';

/**
 * Lists every knowledge collection as a drop target (`appCollectionDropTarget`) while storage
 * items are being dragged. Shown over the storage preview; the Knowledge Sources tab has its
 * own targets for the same drag, so both paths share one drop implementation.
 */
@Component({
    selector: 'app-collection-drop-panel',
    imports: [AppSvgIconComponent, CollectionDropTargetDirective],
    templateUrl: './collection-drop-panel.component.html',
    styleUrls: ['./collection-drop-panel.component.scss'],
})
export class CollectionDropPanelComponent {
    protected readonly loadFailed = signal<boolean>(false);
    protected readonly isVisible = computed(
        () => this.storageDrag.isDragging() && canImportStorageToKnowledge(this.permissionsService)
    );
    protected readonly isLoading = computed(() => !this.collectionsStorage.isCollectionsLoaded() && !this.loadFailed());
    protected readonly itemsLabel = computed(() => {
        const items = this.storageDrag.draggedItems();
        return items.length === 1 ? `"${items[0].name}"` : `${items.length} items`;
    });
    protected readonly likelySkippedCount = computed(
        () => this.storageDrag.draggedItems().filter(isLikelyUnsupportedDocument).length
    );

    /** Loads collections the first time the panel becomes visible; a failed load is retried next time. */
    private readonly loadCollectionsOnFirstShow = effect(() => {
        if (!this.isVisible()) return;
        untracked(() => this.loadCollections());
    });

    protected readonly collectionsStorage = inject(CollectionsStorageService);
    protected readonly documentsStorage = inject(DocumentsStorageService);
    private readonly storageDrag = inject(StorageDragService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly destroyRef = inject(DestroyRef);
    private isLoadRequested = false;

    /** Swallows the drag everywhere on the panel except the collection rows (which claim it first). */
    onPanelDragOver(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
    }

    onPanelDrop(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();
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
