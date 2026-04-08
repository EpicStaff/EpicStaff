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

import { AppSvgIconComponent } from '../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../../../shared/components/buttons/button/button.component';
import { DragDropAreaComponent } from '../../../../../../../shared/components/drag-drop-area/drag-drop-area.component';
import { ListComponent } from '../../../../../../../shared/components/list/list.component';
import { ListActionsComponent } from '../../../../../../../shared/components/list/list-actions/list-actions.component';
import { ListRowComponent } from '../../../../../../../shared/components/list/list-row/list-row.component';
import { FileSizePipe } from '../../../../../../../shared/pipes/file-size.pipe';
import { DisplayedListDocument } from '../../../../../models/document.model';
import { DocumentsStorageService } from '../../../../../services/documents-storage.service';

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
    private readonly documentsStorageService = inject(DocumentsStorageService);

    @ViewChild('fileInput') fileInput!: ElementRef<HTMLInputElement>;
    documents = model<DisplayedListDocument[]>([]);
    filesUploaded = output<FileList>();

    hasInvalidFiles = computed(() => this.documents().some((d) => !d.isValidType || !d.isValidSize));

    onFileSelect(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files) {
            this.filesUploaded.emit(input.files);
            input.value = '';
        }
    }

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
