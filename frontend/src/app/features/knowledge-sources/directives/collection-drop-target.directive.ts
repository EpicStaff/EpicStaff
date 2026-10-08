import { computed, Directive, effect, inject, input, signal } from '@angular/core';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { StorageDragService } from '../../files/services/storage-drag.service';
import { canImportStorageToKnowledge } from '../helpers/storage-import.util';
import { DocumentsStorageService } from '../services/documents-storage.service';

/**
 * Makes the host a native HTML5 drop target that imports the storage items being dragged
 * (`StorageDragService`) into the bound knowledge collection.
 *
 * It only reacts to a live storage drag — OS file drags and any other drag pass through
 * untouched, so an enclosing upload area keeps working. While armed it claims the drag
 * (`preventDefault` + `stopPropagation`), so nested/enclosing handlers never see it.
 *
 * Host classes for styling: `collection-drop-target--armed` (a storage drag is live and the
 * user may import), `--hovered` (the drag is over this target), `--busy` (an import into
 * this collection is in flight; drops are refused).
 *
 * The import runs in the root `DocumentsStorageService`, so it survives the host.
 */
@Directive({
    selector: '[appCollectionDropTarget]',
    host: {
        '[class.collection-drop-target--armed]': 'isArmed()',
        '[class.collection-drop-target--hovered]': 'isHovered()',
        '[class.collection-drop-target--busy]': 'isBusy()',
        '(dragenter)': 'onDragOver($event)',
        '(dragover)': 'onDragOver($event)',
        '(dragleave)': 'onDragLeave($event)',
        '(drop)': 'onDrop($event)',
    },
})
export class CollectionDropTargetDirective {
    /** The collection to import into; `null`/`undefined` disables the target. */
    readonly collectionId = input.required<number | null | undefined>({ alias: 'appCollectionDropTarget' });

    private readonly hovered = signal<boolean>(false);
    private readonly canImport = computed(() => canImportStorageToKnowledge(this.permissionsService));

    protected readonly isArmed = computed(
        () => this.collectionId() != null && this.storageDrag.isDragging() && this.canImport()
    );
    protected readonly isBusy = computed(() => {
        const collectionId = this.collectionId();
        return collectionId != null && this.documentsStorage.isImporting(collectionId);
    });
    protected readonly isHovered = computed(() => this.hovered() && this.isArmed() && !this.isBusy());

    /** A drag can end (Esc, drop elsewhere) without a `dragleave` here; never carry hover into the next one. */
    private readonly clearHoverWhenDragEnds = effect(() => {
        if (!this.storageDrag.isDragging()) this.hovered.set(false);
    });

    private readonly storageDrag = inject(StorageDragService);
    private readonly documentsStorage = inject(DocumentsStorageService);
    private readonly permissionsService = inject(PermissionsService);

    onDragOver(event: DragEvent): void {
        if (!this.isArmed()) return;
        event.preventDefault();
        event.stopPropagation();
        const isBusy = this.isBusy();
        if (event.dataTransfer) event.dataTransfer.dropEffect = isBusy ? 'none' : 'copy';
        this.hovered.set(!isBusy);
    }

    onDragLeave(event: DragEvent): void {
        const host = event.currentTarget as HTMLElement | null;
        const related = event.relatedTarget as Node | null;
        if (host && related && host.contains(related)) return;
        this.hovered.set(false);
    }

    onDrop(event: DragEvent): void {
        if (!this.isArmed()) return;
        event.preventDefault();
        event.stopPropagation();
        this.hovered.set(false);
        const collectionId = this.collectionId();
        if (collectionId == null || this.isBusy()) return;
        // Fire and forget: the service owns the request and the toasts. The drag itself is
        // ended by the source's `dragend`, which fires right after this drop.
        this.documentsStorage.importFromStorage(collectionId, this.storageDrag.draggedItems());
    }
}
