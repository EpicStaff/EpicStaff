import { DOCUMENT } from '@angular/common';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    Injector,
    model,
    output,
    ViewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    DragDropAreaComponent,
    ListActionsComponent,
    ListComponent,
    ListRowComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { isFocusLost } from '@shared/utils';
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
        HasPermissionDirective,
        MatTooltip,
    ],
})
export class FilesListComponent {
    private destroyRef = inject(DestroyRef);
    readonly documentsStorageService = inject(DocumentsStorageService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);

    @ViewChild('fileInput') fileInput!: ElementRef<HTMLInputElement>;
    documents = model<DisplayedListDocument[]>([]);
    filesUploaded = output<FileList>();
    documentSelected = output<DisplayedListDocument>();

    private readonly removeButtons = viewChildren<ElementRef<HTMLButtonElement>>('removeButton');

    hasInvalidFiles = computed(() => this.documents().some((d) => !d.isValidType || !d.isValidSize));

    onFileSelect(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files) {
            this.filesUploaded.emit(input.files);
            input.value = '';
        }
    }

    onDelete(item: DisplayedListDocument): void {
        const { document_id, file_name } = item;
        if (this.documentsStorageService.isDeleting(document_id)) return;
        const index = this.documents().indexOf(item);

        this.confirmationDialogService
            .confirmDelete(file_name)
            .pipe(
                filter((result) => result === true),
                switchMap(() => {
                    if (!document_id) {
                        this.documents.update((docs) => docs.filter((d) => d.file_name !== file_name));
                        this.keepFocusAfterRemoval(index);
                        return [];
                    }
                    return this.documentsStorageService.deleteDocument(document_id);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((res) => {
                if (!res) return;
                this.documents.update((docs) => docs.filter((d) => d.document_id !== document_id));
                this.keepFocusAfterRemoval(index);
            });
    }

    /**
     * The removed row (and, while it is deleted, its spinner) takes the focused Remove button along, which would drop
     * the focus out of the dialog. It moves to the Remove button now in that place, or the last one; once the list is
     * empty this component goes and the step hands the focus to its file picker.
     */
    private keepFocusAfterRemoval(index: number): void {
        afterNextRender(
            () => {
                if (!isFocusLost(this.document)) return;
                const buttons = this.removeButtons();
                buttons[Math.min(index, buttons.length - 1)]?.nativeElement.focus();
            },
            { injector: this.injector }
        );
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
