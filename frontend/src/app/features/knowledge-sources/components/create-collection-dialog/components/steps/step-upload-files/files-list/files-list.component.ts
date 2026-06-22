import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    model,
    output,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    DragDropAreaComponent,
    ListActionsComponent,
    ListComponent,
    ListRowComponent,
} from '@shared/components';
import { filter, switchMap } from 'rxjs';

import { FileSizePipe } from '../../../../../../../../shared/pipes/file-size.pipe';
import { DisplayedListDocument } from '../../../../../../models/document.model';
import { DocumentsStorageService } from '../../../../../../services/documents-storage.service';

@Component({
    selector: 'app-files-list',
    templateUrl: './files-list.component.html',
    styleUrls: ['./files-list.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ButtonComponent,
        AppSvgIconComponent,
        FileSizePipe,
        DragDropAreaComponent,
        ListActionsComponent,
        ListComponent,
        ListRowComponent,
    ],
})
export class FilesListComponent {
    private destroyRef = inject(DestroyRef);
    readonly documentsStorageService = inject(DocumentsStorageService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);

    @ViewChild('fileInput') fileInput!: ElementRef<HTMLInputElement>;
    documents = model<DisplayedListDocument[]>([]);
    filesUploaded = output<FileList>();
    documentSelected = output<DisplayedListDocument>();

    hasInvalidFiles = computed(() => this.documents().some((d) => !d.isValidType || !d.isValidSize));

    onFileSelect(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files) {
            this.filesUploaded.emit(input.files);
            input.value = '';
        }
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
