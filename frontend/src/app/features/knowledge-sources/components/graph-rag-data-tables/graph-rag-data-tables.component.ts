import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    BlobPreviewComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { EMPTY, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, tap } from 'rxjs/operators';

import { GraphTableData, GraphTableSummaryItem } from '../../models/graph-visualization.model';
import { DocumentsApiService } from '../../services/documents-api.service';
import { GraphRagService } from '../../services/graph-rag.service';
import { GraphRagDocumentsStorageService } from '../../services/graph-rag-documents-storage.service';
import { GraphRagGridTableComponent } from '../graph-rag-grid-table/graph-rag-grid-table.component';
import { GraphGridColumnDef } from '../graph-rag-grid-table/graph-rag-grid-table.model';
import { GRAPH_TABLE_COLUMNS } from '../graph-rag-grid-table/graph-rag-table-columns';

type ViewState = 'loading' | 'ready' | 'empty' | 'error';

const TABLE_ICONS: Record<string, string> = {
    entities: 'graph-entities',
    relationships: 'graph-relationships',
    communities: 'graph-communities',
    documents: 'graph-documents',
    text_units: 'graph-text-units',
    community_reports: 'graph-community-reports',
    covariates: 'graph-covariates',
};

@Component({
    selector: 'app-graph-rag-data-tables',
    templateUrl: './graph-rag-data-tables.component.html',
    styleUrls: ['./graph-rag-data-tables.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppSvgIconComponent,
        BlobPreviewComponent,
        GraphRagGridTableComponent,
        LoadingSpinnerComponent,
        SearchComponent,
        SelectComponent,
    ],
})
export class GraphRagDataTablesComponent implements OnInit {
    // 1. Inputs
    readonly ragId = input.required<number>();

    // 3. Signals & Computed
    readonly tables = signal<GraphTableSummaryItem[]>([]);
    readonly activeTable = signal<GraphTableSummaryItem | null>(null);
    readonly columns = signal<string[]>([]);
    readonly rows = signal<Record<string, unknown>[]>([]);
    readonly total = signal(0);
    readonly page = signal(1);
    readonly pageSize = signal(10);
    readonly searchTerm = signal('');
    readonly viewState = signal<ViewState>('loading');
    readonly tableLoading = signal(false);
    readonly errorMessage = signal('');
    readonly summaryLoaded = signal(false);

    readonly totalPages = computed(() => Math.ceil(this.total() / this.pageSize()) || 1);
    readonly activeColumnDefs = signal<GraphGridColumnDef[]>([]);
    readonly isDocumentsTable = computed(() => this.activeTable()?.name === 'documents');

    // Document preview state
    readonly previewBlob = signal<Blob | null>(null);
    readonly previewFileName = signal('');
    readonly previewLoading = signal(false);
    readonly previewError = signal('');
    readonly pageNumbers = computed<(number | '...')[]>(() => {
        const current = this.page();
        const total = this.totalPages();
        const visibleCount = 3;

        if (total <= visibleCount + 2) {
            return Array.from({ length: total }, (_, i) => i + 1);
        }

        const pages = new Set<number>();
        // Always show first and last
        pages.add(1);
        pages.add(total);
        // Show a window of `visibleCount` centered on current, clamped to edges
        const halfWindow = Math.floor(visibleCount / 2);
        let windowStart = Math.max(1, current - halfWindow);
        let windowEnd = windowStart + visibleCount - 1;
        if (windowEnd > total) {
            windowEnd = total;
            windowStart = Math.max(1, windowEnd - visibleCount + 1);
        }
        for (let i = windowStart; i <= windowEnd; i++) {
            pages.add(i);
        }

        const sorted = [...pages].sort((a, b) => a - b);
        const result: (number | '...')[] = [];
        for (let i = 0; i < sorted.length; i++) {
            if (i > 0 && sorted[i] - sorted[i - 1] > 1) {
                result.push('...');
            }
            result.push(sorted[i]);
        }
        return result;
    });

    // 5. Public template-bound
    readonly pageSizeItems: SelectItem<number>[] = [
        { name: '10', value: 10 },
        { name: '25', value: 25 },
        { name: '50', value: 50 },
        { name: '100', value: 100 },
    ];

    // 6. Private fields
    private readonly graphRagService = inject(GraphRagService);
    private readonly documentsApiService = inject(DocumentsApiService);
    private readonly documentsStorage = inject(GraphRagDocumentsStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly searchSubject = new Subject<string>();
    private readonly loadSubject = new Subject<void>();
    private readonly previewSubject = new Subject<number>();

    // 8. Lifecycle hooks
    ngOnInit(): void {
        this.initSearchDebounce();
        this.initLoadPipeline();
        this.initPreviewPipeline();
        this.loadTableSummary();
    }

    // 9. Public methods
    onSelectTable(table: GraphTableSummaryItem): void {
        this.closePreview();
        this.activeTable.set(table);
        this.page.set(1);
        this.searchTerm.set('');
        this.loadTableData();
    }

    onPageChange(newPage: number): void {
        if (newPage < 1 || newPage > this.totalPages()) return;
        this.page.set(newPage);
        this.loadTableData();
    }

    onPageSizeChange(value: unknown): void {
        this.pageSize.set(value as number);
        this.page.set(1);
        this.loadTableData();
    }

    getTableIcon(tableName: string): string {
        return TABLE_ICONS[tableName] ?? 'database';
    }

    onSearchInput(term: string): void {
        this.searchSubject.next(term);
    }

    onDocumentRowClick(row: Record<string, unknown>): void {
        const title = String(row['title'] ?? '');
        const document = this.documentsStorage.documents().find((doc) => doc.file_name === title);
        if (!document) {
            this.previewFileName.set(title);
            this.previewError.set('Document not found. It may have been removed from the collection.');
            return;
        }

        this.previewFileName.set(title);
        this.previewError.set('');
        this.previewBlob.set(null);
        this.previewLoading.set(true);
        this.previewSubject.next(document.document_id);
    }

    closePreview(): void {
        this.previewFileName.set('');
        this.previewBlob.set(null);
        this.previewLoading.set(false);
        this.previewError.set('');
    }

    // 10. Private methods
    private initSearchDebounce(): void {
        this.searchSubject
            .pipe(
                debounceTime(300),
                distinctUntilChanged(),
                tap((term) => {
                    this.searchTerm.set(term);
                    this.page.set(1);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.loadTableData());
    }

    private loadTableSummary(): void {
        this.graphRagService
            .getTableSummary(this.ragId())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (summaryItems: GraphTableSummaryItem[]) => {
                    this.summaryLoaded.set(true);
                    this.tables.set(summaryItems);
                    const firstWithData = summaryItems.find((item) => item.count > 0);
                    if (firstWithData) {
                        this.activeTable.set(firstWithData);
                        this.loadTableData();
                    } else if (summaryItems.length > 0) {
                        this.activeTable.set(summaryItems[0]);
                        this.loadTableData();
                    } else {
                        this.viewState.set('empty');
                    }
                },
                error: () => {
                    this.viewState.set('error');
                    this.errorMessage.set('Failed to load table summary');
                },
            });
    }

    private initPreviewPipeline(): void {
        this.previewSubject
            .pipe(
                switchMap((documentId) => this.documentsApiService.previewDocumentBlob(documentId)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (blob) => {
                    this.previewBlob.set(blob);
                    this.previewLoading.set(false);
                },
                error: () => {
                    this.previewLoading.set(false);
                    this.previewError.set('Failed to load document preview.');
                },
            });
    }

    private initLoadPipeline(): void {
        this.loadSubject
            .pipe(
                tap(() => this.tableLoading.set(true)),
                switchMap(() => {
                    const table = this.activeTable();
                    if (!table) return EMPTY;
                    return this.graphRagService.getTableData(
                        this.ragId(),
                        table.name,
                        this.page(),
                        this.pageSize(),
                        this.searchTerm() || undefined
                    );
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (data: GraphTableData) => {
                    const table = this.activeTable();
                    this.activeColumnDefs.set(table ? (GRAPH_TABLE_COLUMNS[table.name] ?? []) : []);
                    this.columns.set(data.columns);
                    this.rows.set(data.rows);
                    this.total.set(data.total);
                    this.tableLoading.set(false);
                    this.viewState.set(data.total === 0 ? 'empty' : 'ready');
                },
                error: () => {
                    this.tableLoading.set(false);
                    this.viewState.set('error');
                    this.errorMessage.set('Failed to load table data');
                },
            });
    }

    private loadTableData(): void {
        this.loadSubject.next();
    }
}
