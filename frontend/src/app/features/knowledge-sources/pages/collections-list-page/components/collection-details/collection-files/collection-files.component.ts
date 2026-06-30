import { ChangeDetectionStrategy, Component, DestroyRef, inject, model, output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ConfirmationDialogService } from '@shared/components';
import { filter, switchMap } from 'rxjs';

import { ListComponent } from '../../../../../../../shared/components/list/list.component';
import { ListActionsComponent } from '../../../../../../../shared/components/list/list-actions/list-actions.component';
import { ListRowComponent } from '../../../../../../../shared/components/list/list-row/list-row.component';
import { FileSizePipe } from '../../../../../../../shared/pipes/file-size.pipe';
import { DisplayedListDocument } from '../../../../../models/document.model';
import { DocumentsStorageService } from '../../../../../services/documents-storage.service';

@Component({
    selector: 'app-collection-details-files',
    templateUrl: './collection-files.component.html',
    styleUrls: ['./collection-files.component.scss'],
    imports: [AppSvgIconComponent, FileSizePipe, ListActionsComponent, ListComponent, ListRowComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionFilesComponent {
    documents = model<DisplayedListDocument[]>([]);
    downloadRequested = output<number>();
    previewRequested = output<number>();

    readonly documentsStorageService = inject(DocumentsStorageService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private destroyRef = inject(DestroyRef);

    onDownload(id: number): void {
        this.downloadRequested.emit(id);
    }

    onDelete({ document_id, file_name }: DisplayedListDocument): void {
        if (this.documentsStorageService.isDeleting(document_id)) return;

        this.confirmationDialogService
            .confirmDelete(file_name)
            .pipe(
                filter((result) => result === true),
                switchMap(() => {
                    if (!document_id) {
                        this.documents.update((docs) => docs.filter((d) => d.file_name !== file_name));
                        return [];
                    }
                    return this.documentsStorageService.deleteDocument(document_id);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((res) => {
                if (!res) return;
                this.documents.update((docs) => docs.filter((d) => d.document_id !== document_id));
            });
    }
}
