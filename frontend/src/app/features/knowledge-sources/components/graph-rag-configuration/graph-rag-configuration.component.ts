import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    OnInit,
    signal,
    untracked,
    viewChild,
    WritableSignal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    HelpTooltipComponent,
    LoadingSpinnerComponent,
    RadioButtonComponent,
    SelectItem,
} from '@shared/components';
import { ApiErrorItem } from '@shared/models';
import { EMPTY, Observable } from 'rxjs';
import { tap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { IndexingDocumentInfo } from '../../helpers/get-indexing-confirmation-data.util';
import { CollectionGraphRag, CreateGraphRagIndexConfigRequest, GraphRagFileType } from '../../models/graph-rag.model';
import { RagConfiguration } from '../../models/rag-configuration';
import { GraphRagDocumentsStorageService } from '../../services/graph-rag-documents-storage.service';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { GraphRagFilesListComponent, GraphRagIndexMode } from './files-list/files-list.component';
import { AppGraphRagParametersComponent } from './index-parameters/index-parameters.component';

const FORMAT_OPTIONS: SelectItem<GraphRagFileType>[] = [
    { name: 'TXT', value: 'text' },
    { name: 'CSV', value: 'csv' },
    { name: 'JSON', value: 'json' },
];

const INDEX_MODE_OPTIONS: SelectItem<GraphRagIndexMode>[] = [
    { name: 'Update new', value: 'update_new' },
    { name: 'Total re-index', value: 'total_reindex' },
];

@Component({
    selector: 'app-graph-rag-configuration',
    templateUrl: './graph-rag-configuration.component.html',
    styleUrls: ['./graph-rag-configuration.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        RadioButtonComponent,
        GraphRagFilesListComponent,
        AppGraphRagParametersComponent,
        AppSvgIconComponent,
        HelpTooltipComponent,
        LoadingSpinnerComponent,
    ],
})
export class GraphRagConfigurationComponent implements OnInit, RagConfiguration {
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);
    private documentsStorage = inject(GraphRagDocumentsStorageService);
    private pollingService = inject(KnowledgeSourcesPollingService);

    graphRag = input.required<CollectionGraphRag>();
    canIndexChange = input<WritableSignal<boolean>>();

    indexParameters = viewChild.required<AppGraphRagParametersComponent>('indexParameters');

    private allDocuments = this.documentsStorage.documents;
    private pendingDeleteIdsSignal = signal<Set<number>>(new Set());

    checkedDocIds = signal<Set<number>>(new Set());
    selectedFormat = signal<GraphRagFileType>('text');
    indexMode = signal<GraphRagIndexMode>('update_new');
    documentsLoading = signal<boolean>(true);

    documents = computed(() =>
        this.allDocuments().filter((d) => !this.pendingDeleteIdsSignal().has(d.graph_rag_document_id))
    );
    private selectedDocs = computed(() => {
        const checked = this.checkedDocIds();
        return this.documents().filter((d) => checked.has(d.graph_rag_document_id));
    });
    hasNonTxtDocuments = computed(() => this.documents().some((doc) => !doc.file_name.endsWith('.txt')));
    isReadonly = computed(() => this.indexMode() === 'update_new');
    hasUnsavedChanges = computed(() => {
        if (this.pendingDeleteIdsSignal().size > 0) return true;
        if (this.indexMode() !== 'total_reindex') return false;
        return this.indexParameters().hasUnsavedFormChanges();
    });

    readonly formatOptions = FORMAT_OPTIONS;
    readonly indexModeOptions = INDEX_MODE_OPTIONS;

    constructor() {
        // Sync the parent's can-index writable input with local selection state.
        effect(() => {
            this.canIndexChange()?.set(this.checkedDocIds().size > 0);
        });

        // Fires only on `indexMode` transitions. Everything else is untracked so
        // polling refreshes / edits don't re-trigger the reset.
        effect(() => {
            if (this.indexMode() !== 'update_new') return;
            untracked(() => this.applyUpdateNewMode());
        });

        // Reacts to the shared docs list (polling / cross-flow bulk deletes) and
        // prunes pending IDs that no longer refer to an existing doc.
        effect(() => {
            const allIds = new Set(this.allDocuments().map((d) => d.graph_rag_document_id));
            untracked(() => this.pruneOrphanedPendingDeletes(allIds));
        });
    }

    ngOnInit() {
        const graphRag = this.graphRag();
        this.selectedFormat.set(graphRag.index_config.file_type);
        this.documentsStorage.clear();
        this.pendingDeleteIdsSignal.set(new Set());
        this.fetchDocuments(graphRag.graph_rag_id);

        this.pollingService.startGraphRagDocumentsPolling(graphRag.graph_rag_id, graphRag.collection_id);
        this.destroyRef.onDestroy(() => this.pollingService.stopGraphRagDocumentsPolling());
    }

    markPendingDelete(graphRagDocumentId: number): void {
        this.pendingDeleteIdsSignal.update((prev) => {
            if (prev.has(graphRagDocumentId)) return prev;
            const next = new Set(prev);
            next.add(graphRagDocumentId);
            return next;
        });
        this.checkedDocIds.update((prev) => this.removeIds(prev, [graphRagDocumentId]));
    }

    onReIncludeFiles(): void {
        this.documentsStorage
            .reIncludeFiles(this.graphRag().graph_rag_id)
            .pipe(
                tap(() => this.clearPendingDeletes()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => this.toastService.success('Files reinitialized successfully.'),
                error: (err) => {
                    this.toastService.error('Files re-including failed.');
                    console.error('Error re-including files:', err);
                },
            });
    }

    toggleDoc(id: number): void {
        this.checkedDocIds.update((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }

    clearPendingDeletes(): void {
        if (this.pendingDeleteIdsSignal().size === 0) return;
        this.pendingDeleteIdsSignal.set(new Set());
    }

    bulkDeletePending(ragId: number): Observable<{ document_ids: number[] }> {
        const documentIds = this.getPendingDeleteDocumentIds();
        if (documentIds.length === 0) return EMPTY;
        return this.documentsStorage.bulkDeleteDocuments(ragId, documentIds);
    }

    getConfigurationData(): CreateGraphRagIndexConfigRequest | false {
        const params = this.indexParameters();
        if (params.form.invalid || !params.isJsonValid()) {
            this.toastService.error('Form value invalid');
            return false;
        }
        return { ...params.form.value, file_type: this.selectedFormat() };
    }

    shouldSaveConfig(): boolean {
        return this.indexMode() === 'total_reindex';
    }

    setServerValidationErrors(errors: ApiErrorItem[]): void {
        this.indexParameters().setServerErrors(errors);
    }

    getPendingDeleteDocumentIds(): number[] {
        const pending = this.pendingDeleteIdsSignal();
        if (pending.size === 0) return [];
        return this.allDocuments()
            .filter((d) => pending.has(d.graph_rag_document_id))
            .map((d) => d.document_id);
    }

    getIndexingDocuments(): IndexingDocumentInfo[] {
        return this.selectedDocs().map((d) => ({
            configId: d.graph_rag_document_id,
            fileName: d.file_name,
            wasIndexed: d.status === 'completed',
        }));
    }

    private fetchDocuments(ragId: number): void {
        this.documentsStorage
            .fetchDocuments(ragId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: () => this.toastService.error('Failed to get documents'),
                complete: () => this.documentsLoading.set(false),
            });
    }

    private removeIds(source: Set<number>, toRemove: Iterable<number>): Set<number> {
        let mutated = false;
        const next = new Set(source);
        for (const id of toRemove) {
            if (next.delete(id)) mutated = true;
        }
        return mutated ? next : source;
    }

    /**
     * Update-new mode restores everything that was unsaved and
     * drops pending document deletions (files reappear in the list)
     */
    private applyUpdateNewMode(): void {
        this.clearPendingDeletes();

        const indexedIds = new Set(
            this.allDocuments()
                .filter((d) => d.status === 'completed')
                .map((d) => d.graph_rag_document_id)
        );
        if (indexedIds.size === 0) return;

        this.checkedDocIds.update((prev) => this.removeIds(prev, indexedIds));
    }

    private pruneOrphanedPendingDeletes(allIds: Set<number>): void {
        this.pendingDeleteIdsSignal.update((prev) => {
            if (prev.size === 0) return prev;
            let mutated = false;
            const next = new Set(prev);
            for (const id of prev) {
                if (!allIds.has(id)) {
                    next.delete(id);
                    mutated = true;
                }
            }
            return mutated ? next : prev;
        });
    }
}
