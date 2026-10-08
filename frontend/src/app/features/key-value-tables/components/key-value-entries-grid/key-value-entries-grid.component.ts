import { DOCUMENT, formatDate } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    linkedSignal,
    LOCALE_ID,
    output,
    signal,
    TemplateRef,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    CopyButtonComponent,
    PaginationControlsComponent,
    SearchComponent,
} from '@shared/components';
import { DATE_TIME_FORMAT_24H } from '@shared/constants';
import { copyWithFeedback, deepEqual, escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import { AgGridAngular } from 'ag-grid-angular';
import {
    AgGridEvent,
    AllCommunityModule,
    CellEditingStoppedEvent,
    CellKeyDownEvent,
    ColDef,
    FullWidthCellKeyDownEvent,
    GridApi,
    GridOptions,
    GridReadyEvent,
    ICellEditorParams,
    ModuleRegistry,
    SortChangedEvent,
    themeQuartz,
} from 'ag-grid-community';
import {
    concat,
    debounce,
    distinctUntilChanged,
    filter,
    firstValueFrom,
    map,
    Observable,
    of,
    skip,
    switchMap,
    take,
    tap,
    timer,
} from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { copyableValue, editableValue, previewText } from '../../helpers/entry-value-preview';
import {
    KeyValueEntryOrdering,
    KeyValueEntrySortField,
    KeyValueTable,
    KeyValueTableEntry,
    KeyValueTableEntryListItem,
    UpdateKeyValueTableEntryRequest,
} from '../../models/key-value-table.model';
import { KeyValueTablesApiService } from '../../services/key-value-tables-api.service';
import { EntryCellEditorComponent, EntryCellEditorParams } from './entry-cell-editor.component';
import { TemplateCellContext, TemplateCellRendererComponent } from './template-cell-renderer.component';

ModuleRegistry.registerModules([AllCommunityModule]);

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;
const DRAFT_ROW_ID = 'new-entry';
const DRAFT_PLACEHOLDER = 'New entry — removed if left empty';
// A new entry's value until one is typed, as in the old Add entry dialog.
const DRAFT_VALUE_TEXT = 'null';
const INVALID_JSON = 'Value must be valid JSON';
const KEY_REQUIRED = 'Key is required';

// Follows the look of the CDT grid (classification-decision-table-grid), built on app tokens so it follows the
// light theme too.
const ENTRIES_GRID_THEME = themeQuartz.withParams({
    fontFamily: 'var(--font-family)',
    fontSize: 14,
    accentColor: 'var(--accent-color)',
    backgroundColor: 'var(--color-card-background)',
    foregroundColor: 'var(--color-text-primary)',
    headerBackgroundColor: 'var(--color-input-background)',
    headerTextColor: 'var(--color-text-primary)',
    // Quartz's own height, pinned: the page's scroll-padding-top (key-value-tables-page.component.scss) keeps a
    // focused cell clear of the sticky header by this much.
    headerHeight: 48,
    // Every other row a shade off the background, in either theme.
    oddRowBackgroundColor: { ref: 'foregroundColor', mix: 0.03 },
    borderColor: 'var(--color-divider-regular)',
    rowHoverColor: { ref: 'accentColor', mix: 0.06 },
    columnBorder: { style: 'solid', width: 1, color: 'var(--color-divider-regular)' },
    headerColumnBorder: { style: 'solid', width: 1, color: 'var(--color-divider-regular)' },
    // The resize handle's own line sat next to the header column border as a second one; the handle still resizes.
    headerColumnResizeHandleColor: 'transparent',
});

// Sorted by the server (`ordering`); the grid only shows the header state, so rows keep the server's order.
const SERVER_SORTED: ColDef<EntryGridRow> = {
    sortable: true,
    unSortIcon: true,
    sortingOrder: ['asc', 'desc'],
    comparator: () => 0,
};

type EditableColumn = 'key' | 'value';

interface EntryGridRow {
    rowId: string;
    // null on the new-entry row, which lives only here until its key is saved.
    entry: KeyValueTableEntryListItem | null;
    key: string;
    // Value cell text: the server preview, or the new entry's typed JSON.
    preview: string;
    sessionLabel: string | null;
    sessionLink: (string | number)[] | null;
    copyValue: (() => Promise<string>) | null;
    // Why the last commit of a cell failed, shown on that cell until it is saved, cancelled or leaves the page.
    errors: Partial<Record<EditableColumn, string>>;
}

interface EntryDraft {
    key: string;
    valueText: string;
}

// A commit that failed, put back into its editor with the reason the next time that cell opens.
interface RejectedEdit {
    rowId: string;
    column: EditableColumn;
    text: string;
    error: string;
}

function rejectedEditId(rowId: string, column: EditableColumn): string {
    return `${rowId}:${column}`;
}

// Router link to the session that last wrote the entry; null when none is on record (edited by hand, or the
// session was deleted since).
function sessionLink(entry: KeyValueTableEntryListItem): (string | number)[] | null {
    if (entry.updated_by_session === null || entry.updated_by_graph === null) return null;
    return ['/graph', entry.updated_by_graph, 'session', entry.updated_by_session];
}

// "<Flow name>, Session #<id>"; null when no session is on record (edited by hand, or the session was deleted since).
function sessionLabel(entry: KeyValueTableEntryListItem): string | null {
    if (entry.updated_by_session === null || entry.updated_by_graph === null) return null;
    const session = `Session #${entry.updated_by_session}`;
    return entry.updated_by_graph_name ? `${entry.updated_by_graph_name}, ${session}` : session;
}

// Trimmed term to query with. The first value and a cleared term go out at once; typing waits until it
// settles, so each keystroke is not a request.
function settledSearch(rawTerm$: Observable<string>): Observable<string> {
    const term$ = rawTerm$.pipe(map((text) => text.trim()));
    return concat(
        term$.pipe(take(1)),
        term$.pipe(
            skip(1),
            debounce((text) => (text ? timer(SEARCH_DEBOUNCE_MS) : of(0)))
        )
    ).pipe(distinctUntilChanged());
}

// The global exception handler flattens a DRF field error into `message: "key: <reason>"`, so the prefix is
// the only field signal in the body. Several flattened errors ("key: …; value: …") are not one cell's error.
function fieldError(error: HttpErrorResponse): { column: EditableColumn; reason: string } | null {
    const message: unknown = error.error?.message;
    if (error.status !== 400 || typeof message !== 'string' || message.includes('; ')) return null;
    const match = /^(key|value): ([\s\S]*)$/.exec(message);
    return match ? { column: match[1] as EditableColumn, reason: match[2] } : null;
}

// The value typed in the editor, as the old dialog read it: JSON text, parsed; null when it is not JSON.
function parseValue(text: string): { value: unknown } | null {
    try {
        return { value: JSON.parse(text) };
    } catch {
        return null;
    }
}

@Component({
    selector: 'app-key-value-entries-grid',
    imports: [
        AgGridAngular,
        AppSvgIconComponent,
        ButtonComponent,
        CopyButtonComponent,
        PaginationControlsComponent,
        RouterLink,
        SearchComponent,
    ],
    templateUrl: './key-value-entries-grid.component.html',
    styleUrls: ['./key-value-entries-grid.component.scss'],
})
export class KeyValueEntriesGridComponent {
    readonly table = input.required<KeyValueTable>();
    readonly canCreate = input(false);
    readonly canUpdate = input(false);
    readonly canDelete = input(false);

    readonly changed = output<void>();

    readonly keyCell = viewChild.required<TemplateRef<TemplateCellContext<EntryGridRow>>>('keyCell');
    readonly valueCell = viewChild.required<TemplateRef<TemplateCellContext<EntryGridRow>>>('valueCell');
    readonly sessionCell = viewChild.required<TemplateRef<TemplateCellContext<EntryGridRow>>>('sessionCell');
    readonly deleteCell = viewChild.required<TemplateRef<TemplateCellContext<EntryGridRow>>>('deleteCell');
    private readonly gridElement = viewChild.required(AgGridAngular, { read: ElementRef<HTMLElement> });

    // Raw text of the key search in the grid header; filters keys server-side once it settles.
    readonly searchTerm = signal('');
    readonly search = toSignal(settledSearch(toObservable(this.searchTerm)), { initialValue: '' });
    // The id, not the table object: a refreshed tables list (new entry_count) must not re-fetch or reset paging.
    readonly tableId = computed(() => this.table().id);
    // Server-side sort, clicked from the Key / Modified By / Updated headers; kept across a table switch.
    readonly ordering = signal<KeyValueEntryOrdering>('key');
    // Back to page 1 whenever the table, search or sort changes; the pagination controls set it otherwise.
    readonly page = linkedSignal(() => {
        this.tableId();
        this.search();
        this.ordering();
        return 1;
    });
    // Reset on a table switch, so the old table's rows (and their entry ids) never sit under the new heading.
    readonly entries = linkedSignal<number, KeyValueTableEntryListItem[]>({
        source: this.tableId,
        computation: () => [],
    });
    readonly totalCount = linkedSignal({ source: this.tableId, computation: () => 0 });
    // The one new-entry row, above the entries; dropped on a table switch.
    readonly draft = linkedSignal<number, EntryDraft | null>({ source: this.tableId, computation: () => null });
    readonly loading = signal(false);
    // The narrowest the columns go: flex columns at their minimum, the others at their width. The grid is kept at
    // least this wide and the page scrolls sideways instead, since a grid that scrolled sideways itself would be a
    // scroll container its header could not stick out of.
    protected readonly columnsMinWidth = signal(0);
    // Rejected commits by `rowId:column`, kept so no typed text is lost however the editor was left.
    private readonly rejectedEdits = linkedSignal<number, Map<string, RejectedEdit>>({
        source: this.tableId,
        computation: () => new Map(),
    });
    protected readonly gridRows = computed<EntryGridRow[]>(() => {
        const rows = this.entries().map((entry) => this.toRow(entry));
        const draft = this.draft();
        if (!draft) return rows;
        const draftRow: EntryGridRow = {
            rowId: DRAFT_ROW_ID,
            entry: null,
            key: draft.key,
            preview: draft.valueText,
            sessionLabel: null,
            sessionLink: null,
            copyValue: null,
            errors: this.cellErrors(DRAFT_ROW_ID),
        };
        return [draftRow, ...rows];
    });
    protected readonly noRowsTemplate = computed(
        () =>
            `<span class="entries-grid__empty">${this.search() ? 'No entries match your search.' : 'No entries yet'}</span>`
    );
    protected readonly columnDefs = computed<ColDef<EntryGridRow>[]>(() => {
        const columns: ColDef<EntryGridRow>[] = [
            {
                ...SERVER_SORTED,
                colId: 'key',
                field: 'key',
                headerName: 'Key',
                flex: 1,
                minWidth: 160,
                initialSort: 'asc',
                ...this.editableColumn('key', this.keyCell),
            },
            {
                colId: 'value',
                field: 'preview',
                headerName: 'Value',
                flex: 2,
                minWidth: 200,
                // Enter is a new line in the value; the editor commits on Ctrl/Cmd+Enter.
                ...this.editableColumn('value', this.valueCell),
            },
            {
                ...SERVER_SORTED,
                colId: 'session',
                headerName: 'Modified By',
                flex: 1,
                minWidth: 160,
                cellRendererSelector: () => this.templateRenderer(this.sessionCell),
                // The link fills the cell, which takes the editable cells' hover tint; "Manual edit" does not.
                cellClassRules: { 'entries-grid__cell--link': ({ data }) => !!data?.sessionLink },
            },
            {
                ...SERVER_SORTED,
                colId: 'updated_at',
                headerName: 'Updated',
                width: 190,
                valueGetter: ({ data }) => data?.entry?.updated_at ?? null,
                valueFormatter: ({ value }) =>
                    typeof value === 'string' ? formatDate(value, DATE_TIME_FORMAT_24H, this.locale) : '',
                cellClass: 'entries-grid__updated',
            },
        ];
        if (this.canDelete()) {
            columns.push({
                colId: 'actions',
                headerName: '',
                width: 56,
                resizable: false,
                cellClass: 'entries-grid__actions',
                cellRendererSelector: () => this.templateRenderer(this.deleteCell),
            });
        }
        return columns;
    });

    readonly loadEntries = effect((onCleanup) => {
        const page = this.page();
        this.reloadTick();
        this.loading.set(true);
        // Saved rows stay locked until a load started after their save brings the server's version.
        const reloadedSaves = [...this.savedIds];
        const releaseSaves = () => reloadedSaves.forEach((id) => this.releaseSaved(id));
        // Only the load a create or rename started may move focus; a load cancelled or superseded drops it.
        const focusTarget = this.pendingFocus;
        this.pendingFocus = null;
        const subscription = this.keyValueTablesApi
            .getEntries({
                table: this.tableId(),
                search: this.search(),
                ordering: this.ordering(),
                limit: PAGE_SIZE,
                offset: (page - 1) * PAGE_SIZE,
            })
            .subscribe({
                next: (response) => {
                    // Deleting the last entry of the last page leaves it empty: step back one page.
                    if (!response.results.length && page > 1) {
                        this.page.set(page - 1);
                        return;
                    }
                    releaseSaves();
                    this.entries.set(response.results);
                    this.totalCount.set(response.count);
                    this.forgetFullEntriesExcept(response.results);
                    this.forgetRejectedEditsExcept(response.results);
                    this.loading.set(false);
                    if (focusTarget) {
                        afterNextRender(() => this.restoreFocus(focusTarget), { injector: this.injector });
                    }
                },
                error: (error: HttpErrorResponse) => {
                    releaseSaves();
                    this.loading.set(false);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
        // Cancels a stale request when the table, search, sort or page changes before it answers.
        onCleanup(() => subscription.unsubscribe());
    });

    protected readonly pageSize = PAGE_SIZE;
    protected readonly draftPlaceholder = DRAFT_PLACEHOLDER;
    protected readonly gridOptions: GridOptions<EntryGridRow> = {
        theme: ENTRIES_GRID_THEME,
        getRowId: ({ data }) => data.rowId,
        // Edits go to the server; rows change only from its responses.
        readOnlyEdit: true,
        stopEditingWhenCellsLoseFocus: true,
        // Rows come a page at a time from the server; sliding them around on every reload is only noise.
        animateRows: false,
        suppressMultiSort: true,
        suppressColumnVirtualisation: true,
        // As tall as its rows, so the page scrolls instead of the grid. Empty or loading, the grid keeps AG Grid's
        // minimum body height (autoHeightMinBodyHeight), room enough for its overlays.
        domLayout: 'autoHeight',
        // Popup editors (the value editor is taller than a few rows) go in the body, not the grid, which is only as
        // tall as its rows and clips them. AG Grid keeps an open popup on its cell as the page scrolls.
        popupParent: inject(DOCUMENT).body,
        defaultColDef: { sortable: false, resizable: true, suppressMovable: true },
    };

    private readonly reloadTick = signal(0);
    // Full entries (the list has only previews) fetched for copy or edit, or returned by a save; kept while their
    // row is on the page and unchanged, so a second copy or edit does not fetch again.
    private readonly fullEntries = new Map<number, KeyValueTableEntry>();
    private gridApi: GridApi<EntryGridRow> | null = null;
    private savingDraft = false;
    // A row is locked (not editable) while any save of it is in flight, and after its last save until a reload
    // brings the server's version, so a second commit can neither overwrite the first nor start from an old value.
    // Saves in flight per entry id: Tab from a renamed key can send the value while the key is still on its way.
    private readonly savesInFlight = new Map<number, number>();
    // Saved, waiting for the reload.
    private readonly savedIds = new Set<number>();
    // Rows whose saves overlapped: their responses may arrive out of order, so none is kept as the full value.
    private readonly overlappingSaveIds = new Set<number>();
    // The cell to focus again once the reload after a create or rename by key lands, found by row id (its index
    // moves). Taken by the next load that starts.
    private pendingFocus: { rowId: string; column: EditableColumn } | null = null;
    // Whether the last commit came from a key (focus still in the editor) rather than a click elsewhere.
    private lastCommitKeptFocus = false;
    private readonly keyValueTablesApi = inject(KeyValueTablesApiService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);
    private readonly locale = inject(LOCALE_ID);
    private readonly router = inject(Router);
    private readonly document = inject(DOCUMENT);

    protected onGridReady(event: GridReadyEvent<EntryGridRow>): void {
        this.gridApi = event.api;
        this.onColumnsChanged(event);
    }

    protected onColumnsChanged({ api }: AgGridEvent<EntryGridRow>): void {
        const width = api
            .getAllDisplayedColumns()
            .reduce((sum, column) => sum + (column.getFlex() ? column.getMinWidth() : column.getActualWidth()), 0);
        this.columnsMinWidth.set(width);
    }

    // One new-entry row at a time: a second click goes back to its key.
    protected onAdd(): void {
        if (!this.draft()) this.draft.set({ key: '', valueText: DRAFT_VALUE_TEXT });
        afterNextRender(() => this.startEditing(DRAFT_ROW_ID, 'key'), { injector: this.injector });
    }

    protected onSortChanged(event: SortChangedEvent<EntryGridRow>): void {
        const sorted = event.api.getColumnState().find((column) => column.sort);
        if (!sorted) return;
        const field = sorted.colId as KeyValueEntrySortField;
        this.ordering.set(sorted.sort === 'desc' ? `-${field}` : field);
    }

    protected onCellEditingStopped(event: CellEditingStoppedEvent<EntryGridRow>): void {
        const row = event.data;
        const column = event.column.getColId() as EditableColumn;
        // undefined when the edit was cancelled (Esc, or a value that never loaded).
        const text = event.newValue as string | undefined;
        if (!row) return;
        if (!row.entry) {
            // Esc on either cell of the new row drops it whole: nothing is created.
            if (text === undefined) {
                this.dropDraft();
                return;
            }
            this.setRejectedEdit(DRAFT_ROW_ID, column, null);
            this.draft.update(
                (draft) => draft && (column === 'key' ? { ...draft, key: text } : { ...draft, valueText: text })
            );
            // After Tab has opened the next cell of the row, if it did.
            setTimeout(() => {
                if (!this.destroyRef.destroyed) this.saveDraftIfDone();
            });
            return;
        }
        // Esc forgets a rejected edit of the cell; a commit replaces it (a failure puts it back).
        this.setRejectedEdit(row.rowId, column, null);
        if (text === undefined) return;
        if (column === 'key') {
            this.commitKey(row.rowId, row.entry, text);
        } else {
            this.commitValue(row.rowId, row.entry, text);
        }
    }

    // AG Grid's Tab moves from cell to cell, never into a cell's controls, so keys stand in for them: Ctrl/Cmd+C
    // copies a key or value (the same copy as the button), Enter follows the session link or deletes the entry.
    // Enter and F2 on an editable cell still start editing (the grid's own keys).
    protected onCellKeyDown(event: CellKeyDownEvent<EntryGridRow> | FullWidthCellKeyDownEvent<EntryGridRow>): void {
        const keyboardEvent = event.event;
        const entry = event.data?.entry;
        if (!(keyboardEvent instanceof KeyboardEvent) || !('column' in event) || !entry) return;
        if (event.api.getEditingCells().length) return;
        const column = event.column.getColId();
        const isCopy =
            keyboardEvent.key.toLowerCase() === 'c' &&
            (keyboardEvent.ctrlKey || keyboardEvent.metaKey) &&
            !keyboardEvent.shiftKey &&
            !keyboardEvent.altKey;
        if (isCopy && (column === 'key' || column === 'value')) {
            keyboardEvent.preventDefault();
            copyWithFeedback(column === 'key' ? entry.key : this.copyValue(entry), this.toastService);
            return;
        }
        if (keyboardEvent.key !== 'Enter') return;
        const link = sessionLink(entry);
        if (column === 'session' && link) {
            keyboardEvent.preventDefault();
            this.router.navigate(link);
        } else if (column === 'actions' && this.canDelete()) {
            keyboardEvent.preventDefault();
            this.onDelete(entry);
        }
    }

    protected onDelete(entry: KeyValueTableEntryListItem): void {
        this.confirmationDialogService
            .confirmDelete(escapeHtml(entry.key))
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.keyValueTablesApi.deleteEntry(entry.id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success(`Entry "${entry.key}" deleted`);
                    this.afterChange();
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    private editableColumn(
        column: EditableColumn,
        cell: () => TemplateRef<TemplateCellContext<EntryGridRow>>
    ): ColDef<EntryGridRow> {
        return {
            editable: ({ data }) => this.canEdit(data),
            // Tints the whole cell on hover, so double-click to edit is not invisible.
            cellClassRules: {
                'entries-grid__cell--editable': ({ data }) => this.canEdit(data),
                // A save on its way: dimmed with a progress cursor until the reload brings the server's version.
                'entries-grid__cell--saving': ({ data }) => !!data?.entry && this.isLocked(data.entry.id),
            },
            cellRendererSelector: () => this.templateRenderer(cell),
            cellEditor: EntryCellEditorComponent,
            cellEditorParams: ({ data }: ICellEditorParams<EntryGridRow>) => this.editorParams(data, column),
        };
    }

    private templateRenderer(cell: () => TemplateRef<TemplateCellContext<EntryGridRow>>) {
        return { component: TemplateCellRendererComponent, params: { template: cell() } };
    }

    private canEdit(row: EntryGridRow | undefined): boolean {
        if (!row) return false;
        if (!row.entry) return this.canCreate() && !this.savingDraft;
        return this.canUpdate() && !this.isLocked(row.entry.id);
    }

    private editorParams(row: EntryGridRow | undefined, column: EditableColumn): Partial<EntryCellEditorParams> {
        // Kept until the cell is saved, cancelled or leaves the page, not only for this opening.
        const rejected = row ? this.rejectedEdits().get(rejectedEditId(row.rowId, column)) : undefined;
        const error = rejected?.error ?? null;
        const text$ = rejected ? of(rejected.text) : this.editText(row, column);
        return {
            multiline: column === 'value',
            ariaLabel: column === 'key' ? 'Key' : 'Value (JSON)',
            placeholder: column === 'key' && !row?.entry ? DRAFT_PLACEHOLDER : '',
            error,
            text$,
            committed: (keptFocus) => (this.lastCommitKeptFocus = keptFocus),
        };
    }

    private editText(row: EntryGridRow | undefined, column: EditableColumn): Observable<string> {
        if (!row) return of('');
        if (column === 'key') return of(row.key);
        if (!row.entry) return of(this.draft()?.valueText ?? DRAFT_VALUE_TEXT);
        return this.fullEntry(row.entry).pipe(
            map((entry) => editableValue(entry.value)),
            tap({ error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)) })
        );
    }

    private commitKey(rowId: string, entry: KeyValueTableEntryListItem, key: string): void {
        if (key === entry.key) return;
        if (!key.trim()) {
            this.reject({ rowId, column: 'key', text: key, error: KEY_REQUIRED });
            return;
        }
        this.save(rowId, entry, 'key', key, { key });
    }

    private commitValue(rowId: string, entry: KeyValueTableEntryListItem, text: string): void {
        const parsed = parseValue(text);
        if (!parsed) {
            this.reject({ rowId, column: 'value', text, error: INVALID_JSON });
            return;
        }
        const known = this.fullEntries.get(entry.id);
        if (known?.updated_at === entry.updated_at && deepEqual(known.value, parsed.value)) return;
        this.save(rowId, entry, 'value', text, { value: parsed.value });
    }

    private save(
        rowId: string,
        entry: KeyValueTableEntryListItem,
        column: EditableColumn,
        text: string,
        body: UpdateKeyValueTableEntryRequest
    ): void {
        this.startSave(entry.id);
        this.keyValueTablesApi
            .updateEntry(entry.id, body)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                // Reloaded for the server's preview (Postgres formats it, not JSON.stringify); the saved full value
                // stays for re-editing and copying the row, unless another save of the row overlapped this one.
                next: (saved) => {
                    this.endSave(saved.id, saved);
                    this.savedIds.add(saved.id);
                    if (column === 'key' && this.lastCommitKeptFocus) {
                        this.pendingFocus = { rowId: String(saved.id), column };
                    }
                    this.reloadTick.update((tick) => tick + 1);
                },
                error: (error: HttpErrorResponse) => {
                    this.endSave(entry.id, null);
                    this.rejectFromServer(rowId, column, text, error);
                },
            });
    }

    // Creates the new entry once editing has left its row: with a key, or drops the row when the key is empty.
    private saveDraftIfDone(): void {
        const draft = this.draft();
        if (!draft || this.savingDraft || this.isEditingRow(DRAFT_ROW_ID)) return;
        if (!draft.key.trim()) {
            this.dropDraft();
            return;
        }
        const parsed = parseValue(draft.valueText);
        if (!parsed) {
            this.reject({ rowId: DRAFT_ROW_ID, column: 'value', text: draft.valueText, error: INVALID_JSON });
            return;
        }
        this.savingDraft = true;
        // A fresh try: an old key error must not sit next to a new value error.
        this.setRejectedEdit(DRAFT_ROW_ID, 'key', null);
        this.setRejectedEdit(DRAFT_ROW_ID, 'value', null);
        this.keyValueTablesApi
            .createEntry({ table: this.tableId(), key: draft.key, value: parsed.value })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (created) => {
                    this.savingDraft = false;
                    this.fullEntries.set(created.id, created);
                    this.dropDraft();
                    if (this.lastCommitKeptFocus) this.pendingFocus = { rowId: String(created.id), column: 'key' };
                    this.afterChange();
                },
                error: (error: HttpErrorResponse) => {
                    this.savingDraft = false;
                    const column = fieldError(error)?.column ?? 'key';
                    const text = column === 'key' ? draft.key : draft.valueText;
                    this.rejectFromServer(DRAFT_ROW_ID, column, text, error);
                },
            });
    }

    private rejectFromServer(rowId: string, column: EditableColumn, text: string, error: HttpErrorResponse): void {
        const message = extractHttpErrorMessage(error);
        this.reject({ rowId, column, text, error: fieldError(error)?.reason ?? message }, message);
    }

    // Toasts the failure and keeps the rejected text and reason on the cell, so they come back the next time it
    // opens. It reopens at once only when the commit came from a key and the user has not moved on since; after a
    // click elsewhere it stays closed, so focus is not pulled back (the new-entry row tries again on its next commit).
    private reject(rejected: RejectedEdit, toast = rejected.error): void {
        this.toastService.error(toast);
        this.setRejectedEdit(rejected.rowId, rejected.column, rejected);
        // After the grid has finished closing the editor that committed.
        setTimeout(() => {
            if (this.destroyRef.destroyed || !this.lastCommitKeptFocus || !this.focusIsFree()) return;
            if (this.gridApi?.getEditingCells().length) return;
            this.startEditing(rejected.rowId, rejected.column);
        });
    }

    private setRejectedEdit(rowId: string, column: EditableColumn, rejected: RejectedEdit | null): void {
        const id = rejectedEditId(rowId, column);
        if (!rejected && !this.rejectedEdits().has(id)) return;
        this.rejectedEdits.update((edits) => {
            const next = new Map(edits);
            if (rejected) {
                next.set(id, rejected);
            } else {
                next.delete(id);
            }
            return next;
        });
        this.refreshRowSoon(rowId);
    }

    private cellErrors(rowId: string): Partial<Record<EditableColumn, string>> {
        const edits = this.rejectedEdits();
        return {
            key: edits.get(rejectedEditId(rowId, 'key'))?.error,
            value: edits.get(rejectedEditId(rowId, 'value'))?.error,
        };
    }

    private forgetRejectedEditsExcept(entries: KeyValueTableEntryListItem[]): void {
        const shown = new Set([DRAFT_ROW_ID, ...entries.map((entry) => String(entry.id))]);
        const kept = [...this.rejectedEdits()].filter(([, edit]) => shown.has(edit.rowId));
        if (kept.length !== this.rejectedEdits().size) this.rejectedEdits.set(new Map(kept));
    }

    private dropDraft(): void {
        this.draft.set(null);
        this.setRejectedEdit(DRAFT_ROW_ID, 'key', null);
        this.setRejectedEdit(DRAFT_ROW_ID, 'value', null);
    }

    private isLocked(entryId: number): boolean {
        return (this.savesInFlight.get(entryId) ?? 0) > 0 || this.savedIds.has(entryId);
    }

    private startSave(entryId: number): void {
        const inFlight = this.savesInFlight.get(entryId) ?? 0;
        if (inFlight > 0) this.overlappingSaveIds.add(entryId);
        this.savesInFlight.set(entryId, inFlight + 1);
        // No earlier full value of the row may be served while this save is on its way.
        this.fullEntries.delete(entryId);
        this.refreshRowSoon(String(entryId));
    }

    // Keeps the saved entry as the row's full value only when it is the one save of the row that was in flight.
    private endSave(entryId: number, saved: KeyValueTableEntry | null): void {
        const inFlight = (this.savesInFlight.get(entryId) ?? 1) - 1;
        if (inFlight > 0) {
            this.savesInFlight.set(entryId, inFlight);
            return;
        }
        this.savesInFlight.delete(entryId);
        // Anything fetched meanwhile may predate the saves, so it goes too.
        if (saved && !this.overlappingSaveIds.has(entryId)) {
            this.fullEntries.set(entryId, saved);
        } else {
            this.fullEntries.delete(entryId);
        }
        this.overlappingSaveIds.delete(entryId);
        this.refreshRowSoon(String(entryId));
        // The last save failed, but an earlier one landed and its reload was skipped while this one was out. The
        // server has that earlier change, so reload: that brings it and unlocks the row.
        if (!saved && this.savedIds.has(entryId)) this.reloadTick.update((tick) => tick + 1);
    }

    // A reload after a save unlocks the row, unless another save of it is still on its way (its own reload will).
    private releaseSaved(entryId: number): void {
        if (this.savesInFlight.has(entryId)) return;
        this.savedIds.delete(entryId);
        this.refreshRowSoon(String(entryId));
    }

    // The grid refreshes a cell only when its value changes; its error and saving state are not part of it.
    private refreshRowSoon(rowId: string): void {
        afterNextRender(() => this.refreshRow(rowId), { injector: this.injector });
    }

    private refreshRow(rowId: string): void {
        const node = this.gridApi?.getRowNode(rowId);
        if (node) this.gridApi?.refreshCells({ rowNodes: [node], force: true });
    }

    // Focus may be moved for the user only while it is still theirs to give: nowhere, or inside the grid itself
    // (not the header search next to it).
    private focusIsFree(): boolean {
        const active = this.document.activeElement;
        return !active || active === this.document.body || this.gridElement().nativeElement.contains(active);
    }

    // Unless the user has moved on while the reload was on its way: to another field, or to editing another cell.
    private restoreFocus(target: { rowId: string; column: EditableColumn }): void {
        const api = this.gridApi;
        const rowIndex = api?.getRowNode(target.rowId)?.rowIndex;
        if (!api || rowIndex == null || api.getEditingCells().length || !this.focusIsFree()) return;
        api.ensureIndexVisible(rowIndex);
        api.setFocusedCell(rowIndex, target.column);
    }

    private startEditing(rowId: string, column: EditableColumn): boolean {
        const api = this.gridApi;
        const rowIndex = api?.getRowNode(rowId)?.rowIndex;
        if (!api || rowIndex == null) return false;
        api.ensureIndexVisible(rowIndex);
        api.setFocusedCell(rowIndex, column);
        api.startEditingCell({ rowIndex, colKey: column });
        return true;
    }

    private isEditingRow(rowId: string): boolean {
        const api = this.gridApi;
        return !!api?.getEditingCells().some((cell) => api.getDisplayedRowAtIndex(cell.rowIndex)?.id === rowId);
    }

    private fullEntry(entry: KeyValueTableEntryListItem): Observable<KeyValueTableEntry> {
        const known = this.fullEntries.get(entry.id);
        if (known?.updated_at === entry.updated_at && !this.savesInFlight.has(entry.id)) return of(known);
        return this.keyValueTablesApi.getEntry(entry.id).pipe(tap((full) => this.fullEntries.set(full.id, full)));
    }

    private forgetFullEntriesExcept(entries: KeyValueTableEntryListItem[]): void {
        const shown = new Set(entries.map((entry) => entry.id));
        for (const id of this.fullEntries.keys()) {
            if (!shown.has(id)) this.fullEntries.delete(id);
        }
    }

    private toRow(entry: KeyValueTableEntryListItem): EntryGridRow {
        return {
            rowId: String(entry.id),
            entry,
            key: entry.key,
            preview: previewText(entry),
            sessionLabel: sessionLabel(entry),
            sessionLink: sessionLink(entry),
            copyValue: () => this.copyValue(entry),
            errors: this.cellErrors(String(entry.id)),
        };
    }

    private copyValue(entry: KeyValueTableEntryListItem): Promise<string> {
        return firstValueFrom(this.fullEntry(entry).pipe(map((full) => copyableValue(full.value))));
    }

    private afterChange(): void {
        this.reloadTick.update((tick) => tick + 1);
        this.changed.emit();
    }
}
