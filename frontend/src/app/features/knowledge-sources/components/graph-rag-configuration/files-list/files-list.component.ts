import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { AppSvgIconComponent, ButtonComponent, CheckboxComponent } from '@shared/components';

import { FileSizePipe } from '../../../../../shared/pipes/file-size.pipe';
import { GraphRagDocument } from '../../../models/graph-rag-document.model';
import { CollectionsStorageService } from '../../../services/collections-storage.service';

export type GraphRagIndexMode = 'update_new' | 'total_reindex';
interface GraphRagDocumentWithDisabled extends GraphRagDocument {
    disabled: boolean;
}

@Component({
    selector: 'app-graph-rag-files-list',
    templateUrl: './files-list.component.html',
    styleUrls: ['./files-list.component.scss'],
    imports: [ButtonComponent, FileSizePipe, AppSvgIconComponent, CheckboxComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphRagFilesListComponent {
    private collectionsStorage = inject(CollectionsStorageService);

    ragId = input.required<number>();
    documents = input.required<GraphRagDocument[]>();
    checkedDocIds = input.required<Set<number>>();
    indexMode = input<GraphRagIndexMode>('update_new');

    toggleDoc = output<number>();
    pendingDelete = output<number>();
    reIncludeFiles = output<void>();

    documentsWithDisabled = computed<GraphRagDocumentWithDisabled[]>(() =>
        this.documents().map((d) => ({
            ...d,
            disabled: this.indexMode() === 'update_new' && d.status === 'completed',
        }))
    );

    processingIds = this.collectionsStorage.processingConfigIds;

    isProcessing(docId: number): boolean {
        return this.processingIds().has(docId);
    }

    onReIncludeFiles(): void {
        this.reIncludeFiles.emit();
    }

    onDelete(item: GraphRagDocumentWithDisabled): void {
        if (item.disabled) return;
        this.pendingDelete.emit(item.graph_rag_document_id);
    }
}
