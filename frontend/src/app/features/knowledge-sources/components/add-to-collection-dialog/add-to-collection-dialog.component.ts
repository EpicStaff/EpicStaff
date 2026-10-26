import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent, SelectComponent, SelectItem } from '@shared/components';
import { finalize } from 'rxjs/operators';

import { isLikelyUnsupportedDocument } from '../../helpers/storage-import.util';
import { ImportFromStorageResponse, StorageImportCandidate } from '../../models/document.model';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { DocumentsStorageService } from '../../services/documents-storage.service';

/** Pass as the dialog's `ariaLabelledBy` so screen readers announce the title. */
export const ADD_TO_COLLECTION_DIALOG_TITLE_ID = 'add-to-collection-dialog-title';

export interface AddToCollectionDialogData {
    /** Storage items to import; each must carry its storage file id. */
    items: StorageImportCandidate[];
}

@Component({
    selector: 'app-add-to-collection-dialog',
    imports: [AppSvgIconComponent, ButtonComponent, SelectComponent],
    templateUrl: './add-to-collection-dialog.component.html',
    styleUrls: ['./add-to-collection-dialog.component.scss'],
})
export class AddToCollectionDialogComponent implements OnInit {
    protected readonly selectedCollectionId = signal<number | null>(null);
    protected readonly isSubmitting = signal<boolean>(false);
    protected readonly loadFailed = signal<boolean>(false);
    protected readonly isLoading = computed(() => !this.collectionsStorage.isCollectionsLoaded() && !this.loadFailed());
    protected readonly collectionItems = computed<SelectItem[]>(() =>
        this.collectionsStorage.collections().map((collection) => ({
            name: collection.collection_name,
            value: collection.collection_id,
        }))
    );
    protected readonly itemsLabel = computed(() =>
        this.data.items.length === 1 ? `"${this.data.items[0].name}"` : `${this.data.items.length} items`
    );
    protected readonly likelySkippedCount = computed(() => this.data.items.filter(isLikelyUnsupportedDocument).length);

    protected readonly canSubmit = computed(() => this.selectedCollectionId() != null && !this.isSubmitting());

    protected readonly titleId = ADD_TO_COLLECTION_DIALOG_TITLE_ID;

    private readonly data: AddToCollectionDialogData = inject(DIALOG_DATA);
    private readonly dialogRef = inject<DialogRef<ImportFromStorageResponse>>(DialogRef);
    private readonly collectionsStorage = inject(CollectionsStorageService);
    private readonly documentsStorage = inject(DocumentsStorageService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.collectionsStorage
            .getCollections()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => this.loadFailed.set(true) });
    }

    protected selectCollection(value: unknown): void {
        this.selectedCollectionId.set(typeof value === 'number' ? value : null);
    }

    protected onSubmit(): void {
        const collectionId = this.selectedCollectionId();
        if (collectionId == null || this.isSubmitting()) return;

        this.setSubmitting(true);
        // The service owns the request; this subscription only reacts to its outcome.
        this.documentsStorage
            .importFromStorage(collectionId, this.data.items)
            .pipe(
                finalize(() => this.setSubmitting(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((response) => {
                // On failure the storage service already toasted; keep the dialog open to retry.
                if (response) this.dialogRef.close(response);
            });
    }

    protected onClose(): void {
        if (this.isSubmitting()) return;
        this.dialogRef.close();
    }

    /** Blocks Escape/backdrop close while a request is in flight, so the outcome stays visible. */
    private setSubmitting(isSubmitting: boolean): void {
        this.isSubmitting.set(isSubmitting);
        this.dialogRef.disableClose = isSubmitting;
    }
}
