import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, model, output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ConfirmationDialogService,
    ListActionsComponent,
    ListComponent,
    ListRowComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter, switchMap } from 'rxjs';

import { FileSizePipe } from '../../../../../../../shared/pipes/file-size.pipe';
import { filterDocumentsByType } from '../../../../../helpers/filter-documents-by-type.util';
import { DisplayedListDocument } from '../../../../../models/document.model';
import { DocumentsStorageService } from '../../../../../services/documents-storage.service';

@Component({
    selector: 'app-collection-details-files',
    templateUrl: './collection-files.component.html',
    styleUrls: ['./collection-files.component.scss'],
    imports: [
        AppSvgIconComponent,
        FileSizePipe,
        ListActionsComponent,
        ListComponent,
        ListRowComponent,
        MatTooltipModule,
        HasPermissionDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionFilesComponent {
    documents = model<DisplayedListDocument[]>([]);
    /** "Filter by type" choice; `null` shows every type. Only narrows what is listed — `documents` stay whole. */
    readonly fileTypeFilter = input<string | null>(null);
    downloadRequested = output<number>();
    previewRequested = output<number>();

    protected readonly visibleDocuments = computed(() =>
        filterDocumentsByType(this.documents(), this.fileTypeFilter())
    );

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

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
