import { DOCUMENT } from '@angular/common';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    inject,
    Injector,
    input,
    output,
    viewChildren,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, CheckboxComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { isFocusLost } from '@shared/utils';

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
    imports: [
        ButtonComponent,
        FileSizePipe,
        AppSvgIconComponent,
        CheckboxComponent,
        MatTooltipModule,
        HasPermissionDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphRagFilesListComponent {
    private collectionsStorage = inject(CollectionsStorageService);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);

    ragId = input.required<number>();
    documents = input.required<GraphRagDocument[]>();
    checkedDocIds = input.required<Set<number>>();
    indexMode = input<GraphRagIndexMode>('update_new');

    toggleDoc = output<number>();
    pendingDelete = output<number>();
    reIncludeFiles = output<void>();

    private readonly removeButtons = viewChildren<ElementRef<HTMLButtonElement>>('removeButton');

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
        const index = this.documentsWithDisabled().findIndex(
            (document) => document.graph_rag_document_id === item.graph_rag_document_id
        );
        this.pendingDelete.emit(item.graph_rag_document_id);
        this.keepFocusAfterRemoval(index);
    }

    /**
     * The removed row takes its focused Remove button along, which would drop the focus out of the dialog. It moves to
     * the Remove button now in that place (or the last one), skipping the disabled ones.
     */
    private keepFocusAfterRemoval(index: number): void {
        afterNextRender(
            () => {
                if (!isFocusLost(this.document)) return;
                const buttons = this.removeButtons()
                    .map((button) => button.nativeElement)
                    .filter((button) => !button.disabled);
                buttons[Math.min(index, buttons.length - 1)]?.focus();
            },
            { injector: this.injector }
        );
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
