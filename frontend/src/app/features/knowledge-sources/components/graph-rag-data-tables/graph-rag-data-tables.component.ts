import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    BlobPreviewComponent,
    InputNumberComponent,
    LoadingSpinnerComponent,
    SearchComponent,
} from '@shared/components';
import { EMPTY, forkJoin, Subject } from 'rxjs';
import { catchError, debounceTime, switchMap, tap } from 'rxjs/operators';

import {
    GRAPH_NOT_INDEXED_MESSAGE,
    GRAPH_SEARCH_DEBOUNCE_MS,
    GRAPH_SEARCH_MAX_LENGTH,
    GRAPH_TABLE_DEFAULT_PAGE_SIZE,
    GRAPH_TABLE_FALLBACK_ICON,
    GRAPH_TABLE_ICONS,
} from '../../constants/constants';
import { isGraphNotIndexedError } from '../../helpers/graph-not-indexed-error.util';
import { GraphTableData, GraphTableSummaryItem } from '../../models/graph-visualization.model';
import { DocumentsApiService } from '../../services/documents-api.service';
import { GraphRagService } from '../../services/graph-rag.service';
import { GraphRagDocumentsStorageService } from '../../services/graph-rag-documents-storage.service';
import { GraphRagLinkPairsStore } from '../../services/graph-rag-link-pairs.service';
import { GraphRagGridTableComponent } from '../graph-rag-grid-table/graph-rag-grid-table.component';
import { GraphGridActionEvent, GraphGridColumnDef } from '../graph-rag-grid-table/graph-rag-grid-table.model';
import {
    GRAPH_ACTION_VIEW_COMMUNITY,
    GRAPH_ACTION_VIEW_COMMUNITY_REPORT,
    GRAPH_ACTION_VIEW_DOCUMENT,
    GRAPH_TABLE_COLUMNS,
} from '../graph-rag-grid-table/graph-rag-table-columns';
import {
    GraphRagLinkedToPickerComponent,
    LinkedToSelection,
} from '../graph-rag-linked-to-picker/graph-rag-linked-to-picker.component';
import { LINKED_TO_LABEL_BY_TYPE, LinkedToTargetType } from '../graph-rag-linked-to-picker/linked-to-targets';

/** `not-indexed`: the backend answered 409 `graph_not_indexed` — the graph exists but has not been indexed yet. */
type ViewState = 'loading' | 'ready' | 'empty' | 'not-indexed' | 'error';

/**
 * Payload set by the parent tabbed view when the user picks an "Open in" target in the visualization
 * detail panel. It is consumed once: after the summary resolves the picked subject table is opened
 * and its linked-to filter is primed, then the flag flips so re-entering the tab (with pendingOpenIn
 * still set upstream) does not re-apply the same filter.
 */
export interface GraphRagPendingOpenIn {
    subject: LinkedToTargetType;
    linkedToType: LinkedToTargetType;
    linkedToId: string;
}

@Component({
    selector: 'app-graph-rag-data-tables',
    templateUrl: './graph-rag-data-tables.component.html',
    styleUrls: ['./graph-rag-data-tables.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppSvgIconComponent,
        BlobPreviewComponent,
        GraphRagGridTableComponent,
        GraphRagLinkedToPickerComponent,
        InputNumberComponent,
        LoadingSpinnerComponent,
        SearchComponent,
    ],
})
export class GraphRagDataTablesComponent implements OnInit {
    // 1. Inputs
    readonly ragId = input.required<number>();
    readonly pendingOpenIn = input<GraphRagPendingOpenIn | null>(null);

    // 3. Signals & Computed
    readonly tables = signal<GraphTableSummaryItem[]>([]);
    readonly activeTable = signal<GraphTableSummaryItem | null>(null);
    readonly rows = signal<Record<string, unknown>[]>([]);
    readonly total = signal(0);
    readonly page = signal(1);
    readonly pageSize = signal(GRAPH_TABLE_DEFAULT_PAGE_SIZE);
    readonly searchTerm = signal('');
    /** Exact-match filter set by a cross-table jump; cleared on table switch, page-size change, or new search. */
    readonly filterColumn = signal<string | null>(null);
    readonly filterValue = signal<string | null>(null);
    /**
     * "Linked to" cross-table filter set from the picker in the toolbar. Mutually exclusive with the jump
     * filter above — either one is active at a time, never both. Cleared on table switch, new search or
     * when the user opens the jump filter. The paired backend params go together or not at all.
     */
    readonly linkedToType = signal<LinkedToTargetType | null>(null);
    readonly linkedToId = signal<string | null>(null);
    readonly viewState = signal<ViewState>('loading');
    readonly tableLoading = signal(false);
    readonly errorMessage = signal('');
    readonly summaryLoaded = signal(false);
    /**
     * Allowed target tables for the currently active subject table — passed to the picker. The
     * link-pairs store owns the matrix and narrows it to the `LinkedToTargetType` union.
     */
    readonly allowedTargetsForActive = computed<readonly LinkedToTargetType[]>(() =>
        this.linkPairsStore.targetsForSubject(this.activeTable()?.name ?? '')
    );

    /** The term as sent to the backend and highlighted in the cells; the field itself keeps what the user typed. */
    readonly trimmedSearchTerm = computed(() => this.searchTerm().trim());
    readonly noSearchMatches = computed(() => this.viewState() === 'empty' && this.trimmedSearchTerm() !== '');
    readonly totalPages = computed(() => Math.ceil(this.total() / this.pageSize()) || 1);
    readonly activeColumnDefs = signal<GraphGridColumnDef[]>([]);
    /** The jump filter's integer value, displayed in the breadcrumb when a cross-table jump is active. */
    readonly filterBreadcrumbValue = computed(() => this.filterValue());
    /** The linked-to breadcrumb's human-readable target label; only present when both type and id are set. */
    readonly linkedToBreadcrumb = computed(() => {
        const type = this.linkedToType();
        const id = this.linkedToId();
        if (!type || !id) return null;
        return { typeLabel: LINKED_TO_LABEL_BY_TYPE[type], id };
    });

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
    protected readonly searchMaxLength = GRAPH_SEARCH_MAX_LENGTH;

    // 6. Private fields
    private readonly graphRagService = inject(GraphRagService);
    private readonly documentsApiService = inject(DocumentsApiService);
    private readonly documentsStorage = inject(GraphRagDocumentsStorageService);
    private readonly linkPairsStore = inject(GraphRagLinkPairsStore);
    private readonly destroyRef = inject(DestroyRef);
    private readonly searchSubject = new Subject<string>();
    private readonly loadSubject = new Subject<void>();
    private readonly previewSubject = new Subject<number>();
    /** Guards single-shot consumption: `pendingOpenIn` is applied at most once per mount. */
    private pendingOpenInConsumed = false;

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
        this.clearFilter();
        this.loadTableData();
    }

    onPageChange(newPage: number): void {
        if (newPage < 1 || newPage > this.totalPages()) return;
        this.page.set(newPage);
        this.loadTableData();
    }

    onPageSizeChange(value: number | null): void {
        // The stepper commits on blur/Enter with the value already clamped to [1, 100], so null should
        // never reach this handler; guard anyway.
        if (value === null) return;
        if (value === this.pageSize()) return;
        this.pageSize.set(value);
        this.page.set(1);
        this.loadTableData();
    }

    getTableIcon(tableName: string): string {
        return GRAPH_TABLE_ICONS[tableName] ?? GRAPH_TABLE_FALLBACK_ICON;
    }

    onSearchInput(term: string): void {
        this.searchSubject.next(term);
    }

    /** Routes a per-row action button from the grid to its handler. */
    onGridAction(event: GraphGridActionEvent): void {
        switch (event.action) {
            case GRAPH_ACTION_VIEW_DOCUMENT:
                this.openDocumentPreview(event.row);
                return;
            case GRAPH_ACTION_VIEW_COMMUNITY_REPORT:
                this.jumpToTable('community_reports', 'community', event.row['community']);
                return;
            case GRAPH_ACTION_VIEW_COMMUNITY:
                this.jumpToTable('communities', 'community', event.row['community']);
                return;
        }
    }

    /** Clears the cross-table jump filter while staying on the current tab. */
    clearJumpFilter(): void {
        this.clearFilter();
        this.page.set(1);
        this.loadTableData();
    }

    /** Applies a "linked to" cross-table filter from the picker, replacing any active jump filter. */
    onLinkedToPicked(selection: LinkedToSelection): void {
        // Mutually exclusive with the jump filter — clear it when the user picks a linked-to row.
        this.filterColumn.set(null);
        this.filterValue.set(null);
        this.linkedToType.set(selection.type);
        this.linkedToId.set(selection.id);
        this.page.set(1);
        this.loadTableData();
    }

    /** Clears the linked-to filter while staying on the current tab. */
    clearLinkedTo(): void {
        this.linkedToType.set(null);
        this.linkedToId.set(null);
        this.page.set(1);
        this.loadTableData();
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
                // No distinctUntilChanged: selecting another table clears the term without going through
                // this stream, so retyping the previous term must still search; switchMap cancels stale loads.
                debounceTime(GRAPH_SEARCH_DEBOUNCE_MS),
                tap((term) => {
                    this.searchTerm.set(term);
                    this.page.set(1);
                    // Drop the cross-table jump filter on new input (the two are never shown
                    // together), but keep any active linked-to filter — the linked-to
                    // breadcrumb renders its own search so users can narrow by name within it.
                    this.filterColumn.set(null);
                    this.filterValue.set(null);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.loadTableData());
    }

    private loadTableSummary(): void {
        // The summary drives the view; the link-pairs matrix only decides which linked-to tabs show.
        // Running them in parallel saves a round-trip; the store swallows link-pairs failures to {},
        // so the picker simply has no allowed targets and is hidden.
        forkJoin({
            summary: this.graphRagService.getTableSummary(this.ragId()),
            pairs: this.linkPairsStore.ensureLoaded(),
        })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ summary }) => {
                    this.summaryLoaded.set(true);
                    this.tables.set(summary);
                    if (summary.length === 0) {
                        this.viewState.set('empty');
                        return;
                    }
                    const pending = this.pendingOpenIn();
                    if (pending && !this.pendingOpenInConsumed) {
                        this.pendingOpenInConsumed = true;
                        const targetTable = summary.find((item) => item.name === pending.subject);
                        if (targetTable) {
                            this.activeTable.set(targetTable);
                            this.linkedToType.set(pending.linkedToType);
                            this.linkedToId.set(pending.linkedToId);
                            this.loadTableData();
                            return;
                        }
                    }
                    const firstWithData = summary.find((item) => item.count > 0);
                    this.activeTable.set(firstWithData ?? summary[0]);
                    this.loadTableData();
                },
                error: (error: HttpErrorResponse) => this.handleLoadError(error, 'Failed to load table summary'),
            });
    }

    private initPreviewPipeline(): void {
        this.previewSubject
            .pipe(
                // Errors are handled per request so a failed preview does not end the stream.
                switchMap((documentId) =>
                    this.documentsApiService.previewDocumentBlob(documentId).pipe(
                        tap((blob) => {
                            this.previewBlob.set(blob);
                            this.previewLoading.set(false);
                        }),
                        catchError(() => {
                            this.previewLoading.set(false);
                            this.previewError.set('Failed to load document preview.');
                            return EMPTY;
                        })
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    private initLoadPipeline(): void {
        this.loadSubject
            .pipe(
                // Errors are handled per request so a failed load does not end the stream.
                switchMap(() => {
                    const table = this.activeTable();
                    if (!table) return EMPTY;
                    // A ready grid stays on screen under the loading overlay; an error, hint or empty message
                    // has no grid to overlay, so it gives way to the full loading state until the answer arrives.
                    if (this.viewState() !== 'ready') {
                        this.viewState.set('loading');
                    }
                    this.tableLoading.set(true);
                    return this.graphRagService
                        .getTableData({
                            ragId: this.ragId(),
                            tableName: table.name,
                            page: this.page(),
                            pageSize: this.pageSize(),
                            search: this.trimmedSearchTerm() || undefined,
                            filterColumn: this.filterColumn() ?? undefined,
                            filterValue: this.filterValue() ?? undefined,
                            linkedToType: this.linkedToType() ?? undefined,
                            linkedToId: this.linkedToId() ?? undefined,
                        })
                        .pipe(
                            tap((data) => this.applyTableData(table, data)),
                            catchError((error: HttpErrorResponse) => {
                                this.tableLoading.set(false);
                                this.handleLoadError(error, 'Failed to load table data');
                                return EMPTY;
                            })
                        );
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    private applyTableData(table: GraphTableSummaryItem, data: GraphTableData): void {
        this.activeColumnDefs.set(GRAPH_TABLE_COLUMNS[table.name] ?? []);
        this.rows.set(data.rows);
        this.total.set(data.total);
        this.tableLoading.set(false);
        this.viewState.set(data.total === 0 ? 'empty' : 'ready');
    }

    private openDocumentPreview(row: Record<string, unknown>): void {
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

    /** Switches to `tableName` and applies an exact-match filter on `columnKey`; no-op when the value is missing. */
    private jumpToTable(tableName: string, columnKey: string, rawValue: unknown): void {
        if (rawValue == null) return;
        const destination = this.tables().find((table) => table.name === tableName);
        if (!destination) return;
        this.closePreview();
        this.activeTable.set(destination);
        this.page.set(1);
        this.searchTerm.set('');
        // Exact match avoids the substring over-match that short integer values like a community number cause
        // (e.g. "7" would otherwise match 7, 17, 70, 700…).
        this.filterColumn.set(columnKey);
        this.filterValue.set(String(rawValue));
        // The jump filter and the linked-to filter are mutually exclusive — opening one closes the other.
        this.linkedToType.set(null);
        this.linkedToId.set(null);
        this.loadTableData();
    }

    /** "Graph not indexed" gets the run-indexing hint; anything else (other 409s and 404 included) is a load error. */
    private handleLoadError(error: HttpErrorResponse, fallbackMessage: string): void {
        if (isGraphNotIndexedError(error)) {
            this.viewState.set('not-indexed');
            this.errorMessage.set(GRAPH_NOT_INDEXED_MESSAGE);
        } else {
            this.viewState.set('error');
            this.errorMessage.set(fallbackMessage);
        }
    }

    private loadTableData(): void {
        this.loadSubject.next();
    }

    /** Clears every exclusive filter (jump + linked-to). Called on table switch, new search, or clearing either. */
    private clearFilter(): void {
        this.filterColumn.set(null);
        this.filterValue.set(null);
        this.linkedToType.set(null);
        this.linkedToId.set(null);
    }
}
