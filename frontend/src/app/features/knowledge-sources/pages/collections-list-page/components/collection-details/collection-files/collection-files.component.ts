import {ChangeDetectionStrategy, Component, DestroyRef, inject, input, model} from "@angular/core";
import {AppSvgIconComponent} from "../../../../../../../shared/components/app-svg-icon/app-svg-icon.component";
import {FileSizePipe} from "../../../../../../../shared/pipes/file-size.pipe";
import {
    ListActionsComponent
} from "../../../../../../../shared/components/list/list-actions/list-actions.component";
import {ListComponent} from "../../../../../../../shared/components/list/list.component";
import {ListRowComponent} from "../../../../../../../shared/components/list/list-row/list-row.component";
import {DisplayedListDocument} from "../../../../../models/document.model";
import {DocumentsStorageService} from "../../../../../services/documents-storage.service";
import {takeUntilDestroyed} from "@angular/core/rxjs-interop";

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
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CollectionFilesComponent{
    documents = model<DisplayedListDocument[]>([]);

    private documentsStorageService = inject(DocumentsStorageService);
    private destroyRef = inject(DestroyRef);

    onDelete({document_id, file_name}: DisplayedListDocument): void {
        if (!document_id) {
            this.documents.update(document => {
                return document.filter((d) => d.file_name !== file_name);
            });
            return;
        }

        this.documentsStorageService.deleteDocumentById(document_id).pipe(
            takeUntilDestroyed(this.destroyRef)
        ).subscribe((res) => {
            if (!res) return;

            this.documents.update(document => {
                return document.filter((d) => d.document_id !== document_id);
            });
        })
    }
}
