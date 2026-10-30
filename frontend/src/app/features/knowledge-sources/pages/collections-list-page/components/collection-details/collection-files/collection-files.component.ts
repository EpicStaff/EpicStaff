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
    input,
    model,
    output,
    viewChildren,
} from '@angular/core';
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
import { isFocusLost } from '@shared/utils';
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

    private readonly removeButtons = viewChildren<ElementRef<HTMLButtonElement>>('removeButton');

    protected readonly visibleDocuments = computed(() =>
        filterDocumentsByType(this.documents(), this.fileTypeFilter())
    );

    readonly documentsStorageService = inject(DocumentsStorageService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);

    onPreview({ document_id }: DisplayedListDocument): void {
        if (document_id) this.previewRequested.emit(document_id);
    }

    onDownload(id: number): void {
        this.downloadRequested.emit(id);
    }

    onDelete(item: DisplayedListDocument): void {
        const { document_id, file_name } = item;
        if (this.documentsStorageService.isDeleting(document_id)) return;
        const index = this.visibleDocuments().indexOf(item);

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
     * the focus to the page. It moves to the Remove button now in that place, or the last one.
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

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
