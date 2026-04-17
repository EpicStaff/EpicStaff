import { ChangeDetectionStrategy, Component, DestroyRef, inject, input, model } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ListActionsComponent,
    ListComponent,
    ListRowComponent,
} from '@shared/components';
import { switchMap, tap } from 'rxjs/operators';

import { ToastService } from '../../../../../services/notifications';
import { FileSizePipe } from '../../../../../shared/pipes/file-size.pipe';
import { GraphRagDocument } from '../../../models/graph-rag.model';
import { GraphRagService } from '../../../services/graph-rag.service';

@Component({
    selector: 'app-graph-rag-files-list',
    templateUrl: './files-list.component.html',
    styleUrls: ['./files-list.component.scss'],
    imports: [
        ButtonComponent,
        FileSizePipe,
        ListActionsComponent,
        ListComponent,
        ListRowComponent,
        AppSvgIconComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphRagFilesListComponent {
    private toastService = inject(ToastService);
    private graphRagService = inject(GraphRagService);
    private destroyRef = inject(DestroyRef);

    ragId = input.required<number>();
    documents = model.required<GraphRagDocument[]>();

    reIncludeFiles(): void {
        const ragId = this.ragId();
        this.graphRagService
            .reIncludeFiles(ragId)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => this.graphRagService.getRagById(ragId)),
                tap((graphRag) => this.documents.set(graphRag.documents))
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
