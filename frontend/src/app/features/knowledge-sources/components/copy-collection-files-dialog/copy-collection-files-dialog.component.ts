import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { AppSvgIconComponent, MultiSelectComponent, MultiSelectTriggerDirective, SelectItem } from '@shared/components';

import { GetCollectionRequest } from '../../models/collection.model';
import { CollectionDocument } from '../../models/document.model';
import { DocumentsStorageService } from '../../services/documents-storage.service';

export interface CopyCollectionFilesDialogData {
    sourceCollectionId: number;
    documents: CollectionDocument[];
    allCollections: GetCollectionRequest[];
}

@Component({
    selector: 'app-copy-collection-files-dialog',
    templateUrl: './copy-collection-files-dialog.component.html',
    styleUrls: ['./copy-collection-files-dialog.component.scss'],
    imports: [AppSvgIconComponent, ButtonComponent, MultiSelectComponent, MultiSelectTriggerDirective],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyCollectionFilesDialogComponent {
    readonly data: CopyCollectionFilesDialogData = inject(DIALOG_DATA);

    private dialogRef = inject(DialogRef);
    private destroyRef = inject(DestroyRef);
    private documentsStorageService = inject(DocumentsStorageService);

    selectedDocumentIds = signal<number[]>([]);
    selectedCollectionIds = signal<number[]>([]);

    fileItems = computed<SelectItem[]>(() =>
        this.data.documents.map((doc) => ({
            name: doc.file_name,
            value: doc.document_id,
        }))
    );

    collectionItems = computed<SelectItem[]>(() =>
        this.data.allCollections
            .filter((c) => c.collection_id !== this.data.sourceCollectionId)
            .map((c) => ({
                name: c.collection_name,
                value: c.collection_id,
            }))
    );

    canCopy = computed(() => this.selectedDocumentIds().length > 0 && this.selectedCollectionIds().length > 0);

    onCopy(): void {
        if (!this.canCopy()) return;

        this.documentsStorageService
            .copyDocumentsToCollections(
                this.selectedDocumentIds() as number[],
                this.selectedCollectionIds() as number[]
            )
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.dialogRef.close());
    }

    onClose(): void {
        this.dialogRef.close();
    }
}
