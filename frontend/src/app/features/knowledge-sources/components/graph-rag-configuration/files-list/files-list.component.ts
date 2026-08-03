import { ChangeDetectionStrategy, Component, DestroyRef, inject, input, model, output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent, CheckboxComponent } from '@shared/components';
import { switchMap, tap } from 'rxjs/operators';

import { ToastService } from '../../../../../services/notifications';
import { FileSizePipe } from '../../../../../shared/pipes/file-size.pipe';
import { GraphRagDocument } from '../../../models/graph-rag-document.model';
import { GraphRagService } from '../../../services/graph-rag.service';

@Component({
    selector: 'app-graph-rag-files-list',
    templateUrl: './files-list.component.html',
    styleUrls: ['./files-list.component.scss'],
    imports: [ButtonComponent, FileSizePipe, AppSvgIconComponent, CheckboxComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphRagFilesListComponent {
    private toastService = inject(ToastService);
    private graphRagService = inject(GraphRagService);
    private destroyRef = inject(DestroyRef);

    ragId = input.required<number>();
    documents = model.required<GraphRagDocument[]>();
    checkedDocIds = input.required<Set<number>>();
    toggleDoc = output<number>();

    reIncludeFiles(): void {
        const ragId = this.ragId();
        this.graphRagService
            .reIncludeFiles(ragId)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => this.graphRagService.getRagDocuments(ragId)),
                tap((docs) => this.documents.set(docs.documents))
            )
            .subscribe({
                next: () => {
                    this.toastService.success('Files reinitialized successfully.');
                },
                error: (err) => {
                    this.toastService.error('Files re-including failed.');
                    console.error('Error re-including files:', err);
                },
            });
    }

    onDelete(id: number): void {
        const ragId = this.ragId();
        this.graphRagService
            .deleteFileById(ragId, id)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(() =>
                    this.documents.update((prev) => {
                        return prev.filter((d) => d.document_id !== id);
                    })
                )
            )
            .subscribe({
                next: () => {
                    this.toastService.success('File deleted successfully.');
                },
                error: (e) => {
                    this.toastService.error('File delete failed.');
                    console.log('File deleting error:', e);
                },
            });
    }
}
