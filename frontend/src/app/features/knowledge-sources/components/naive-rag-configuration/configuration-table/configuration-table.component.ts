import { KeyValuePipe } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    inject,
    input,
    model,
    output,
    signal,
} from '@angular/core';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CheckboxComponent,
    InputNumberComponent,
    MultiSelectComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';

import { CHUNK_STRATEGIES_SELECT_ITEMS, FILE_TYPES } from '../../../constants/constants';
import { NaiveRagChunkStrategy } from '../../../enums/naive-rag-chunk-strategy';
import { RunNaiveRagDocumentChunkingRequest } from '../../../models/naive-rag-document.model';
import { CollectionsStorageService } from '../../../services/collections-storage.service';
import { NaiveRagDocumentsStorageService } from '../../../services/naive-rag-documents-storage.service';
import { DocumentStatusFilter, TableDocument } from './configuration-table.interface';

@Component({
    selector: 'app-configuration-table',
    templateUrl: './configuration-table.component.html',
    styleUrls: ['./configuration-table.component.scss'],
    imports: [
        SelectComponent,
        AppSvgIconComponent,
        ButtonComponent,
        InputNumberComponent,
        CheckboxComponent,
        MultiSelectComponent,
        KeyValuePipe,
        MATERIAL_FORMS,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConfigurationTableComponent {
    fileTypeSelectItems: SelectItem[] = FILE_TYPES.map((t) => ({ name: t, value: t }));
    chunkStrategySelectItems: SelectItem[] = CHUNK_STRATEGIES_SELECT_ITEMS;

    private documentsStorageService = inject(NaiveRagDocumentsStorageService);
    private collectionsStorage = inject(CollectionsStorageService);

    searchTerm = input<string>('');
    showBulkRow = input<boolean>(false);
    statusFilter = input<DocumentStatusFilter>('all');
    ragId = input.required<number>();
    documents = this.documentsStorageService.documents;
    pendingDocIds = this.documentsStorageService.pendingDocIds;
    processingConfigIds = this.collectionsStorage.processingConfigIds;
    selectedRagDocId = model<number | null>(null);

    // Backend never finalizes a document's own `status` when indexing is cancelled
    // (it stays 'processing' forever) — fall back to the rag-level status, which the
    // "Stop indexing" button already relies on, so the per-row spinner disappears in
    // step with the button once the rag itself is no longer processing. Matches
    // NaiveRagStrategy/GraphRagStrategy.isIndexing's not-found convention (`false`) —
    // safe because startIndexing() optimistically marks the rag via
    // markRagAsProcessing() in the same tick a document can first become 'processing'.
    private ragIsProcessing = computed(
        () => this.collectionsStorage.getRagStatus(this.ragId(), 'naive') === 'processing'
    );

    docsCheckChange = output<number[]>();
    applyBulkUpdate = output<Partial<RunNaiveRagDocumentChunkingRequest>>();
    onTuneChunk = output<{ ragDocumentId: number; allDocumentIds: number[] }>();

    bulkChunkStrategy = signal<string | null>(null);
    bulkChunkSize = signal<number | null>(null);
    bulkChunkOverlap = signal<number | null>(null);
    fileTypeFilter = signal<string[]>([]);
    chunkStrategyFilter = signal<string[]>([]);

    allChecked = computed(() => {
        const arr = this.filteredDocuments();
        return arr.length > 0 && arr.every((r) => r.checked);
    });
    checkedDocumentIds = computed(() =>
        this.filteredDocuments()
            .filter((d) => d.checked)
            .map((d) => d.naive_rag_document_id)
    );
    indeterminate = computed(() => !!this.checkedDocumentIds().length && !this.allChecked());

    filteredDocuments = computed<TableDocument[]>(() => {
        let data = this.documents();

        data = this.applyFileNameFilter(data);
        data = this.applyFileTypeFilter(data);
        data = this.applyChunkStrategyFilter(data);
        data = this.applyStatusFilter(data);

        return data;
    });

    constructor() {
        effect(() => {
            this.docsCheckChange.emit(this.checkedDocumentIds());
        });
    }

    isRowProcessing(d: TableDocument): boolean {
        if (!this.ragIsProcessing()) return false;
        if (d.status === 'completed' || d.status === 'failed' || d.status === 'outdated') return false;
        return this.processingConfigIds().has(d.naive_rag_document_id) || d.status === 'processing';
    }

    onDocFieldChange(
        document: TableDocument,
        field: keyof RunNaiveRagDocumentChunkingRequest,
        value: string | number | null
    ): void {
        this.documentsStorageService.setPendingField(document.naive_rag_document_id, field, value);
    }

    onChunkStrategyChange(document: TableDocument, value: unknown): void {
        if (typeof value !== 'string') return;
        this.onDocFieldChange(document, 'chunk_strategy', value);
    }

    revert(documentId: number): void {
        this.documentsStorageService.clearPending([documentId]);
    }

    hasPending(documentId: number): boolean {
        return this.pendingDocIds().has(documentId);
    }

    onFileTypeFilterChange(value: unknown[]): void {
        this.fileTypeFilter.set(value.filter((v): v is string => typeof v === 'string'));
    }

    onChunkStrategyFilterChange(value: unknown[]): void {
        this.chunkStrategyFilter.set(value.filter((v): v is string => typeof v === 'string'));
    }

    toggleAll() {
        const all = this.allChecked();
        const ids = this.filteredDocuments().map((d) => d.naive_rag_document_id);
        this.documentsStorageService.toggleAll(all, ids);
    }

    toggleDocument(item: TableDocument) {
        this.documentsStorageService.toggleDocument(item.naive_rag_document_id);
    }

    parseFullFileName(fullName: string): { name: string; type: string } {
        const parts = fullName.split('.');
        const type = parts.pop()!;

        return {
            name: parts.join('.'),
            type: '.' + type,
        };
    }

    tuneChunk(ragDocumentId: number) {
        const allDocumentIds = this.filteredDocuments().map((d) => d.naive_rag_document_id);
        this.onTuneChunk.emit({ ragDocumentId, allDocumentIds });
    }

    onApplyBulkEdit() {
        const patch: Partial<RunNaiveRagDocumentChunkingRequest> = {};

        const strategy = this.bulkChunkStrategy();
        if (strategy) patch.chunk_strategy = strategy as NaiveRagChunkStrategy;

        const size = this.bulkChunkSize();
        if (size !== null) patch.chunk_size = size;

        const overlap = this.bulkChunkOverlap();
        if (overlap !== null) patch.chunk_overlap = overlap;

        this.applyBulkUpdate.emit(patch);
    }

    // ================= FILTER LOGIC START =================

    private applyFileNameFilter(data: TableDocument[]): TableDocument[] {
        const term = this.searchTerm();

        return data.filter((d) => {
            return d.file_name.toLowerCase().includes(term.toLowerCase());
        });
    }

    private applyFileTypeFilter(data: TableDocument[]): TableDocument[] {
        const filesFilter = this.fileTypeFilter();
        if (!filesFilter.length) return data;

        return data.filter((d) => {
            const ext = d.file_name.split('.').pop()?.toLowerCase();
            return ext && filesFilter.includes(ext);
        });
    }

    private applyChunkStrategyFilter(data: TableDocument[]): TableDocument[] {
        const strategyFilter = this.chunkStrategyFilter();
        if (!strategyFilter.length) return data;

        return data.filter((d) => strategyFilter.includes(d.chunk_strategy));
    }

    private applyStatusFilter(data: TableDocument[]): TableDocument[] {
        switch (this.statusFilter()) {
            case 'issues':
                return data.filter((d) => d.status === 'failed' || d.status === 'outdated');
            case 'not_indexed':
                return data.filter((d) => d.status !== 'completed' && d.status !== 'failed' && d.status !== 'outdated');
            case 'indexed':
                return data.filter((d) => d.status === 'completed');
            default:
                return data;
        }
    }

    // ================= FILTER LOGIC END =================
}
