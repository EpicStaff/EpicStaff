import { ChangeDetectionStrategy, Component, DestroyRef, inject, model } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent } from '@shared/components';

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

    private documentsStorageService = inject(DocumentsStorageService);
    private destroyRef = inject(DestroyRef);

    onDelete({ document_id, file_name }: DisplayedListDocument): void {
        if (!document_id) {
            this.documents.update((document) => {
                return document.filter((d) => d.file_name !== file_name);
            });
            return;
        }

        this.documentsStorageService
            .deleteDocumentById(document_id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((res) => {
                if (!res) return;

                this.documents.update((document) => {
                    return document.filter((d) => d.document_id !== document_id);
                });
            });
    }
}
