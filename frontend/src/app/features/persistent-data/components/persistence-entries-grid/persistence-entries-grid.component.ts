import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, effect, inject, input, linkedSignal, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    AppTableRowAction,
    ButtonComponent,
    ConfirmationDialogService,
    CopyButtonComponent,
    PaginationControlsComponent,
    TableRow,
} from '@shared/components';
import { DATE_TIME_FORMAT_24H } from '@shared/constants';
import { extractHttpErrorMessage } from '@shared/utils';
import {
    concat,
    debounce,
    distinctUntilChanged,
    filter,
    map,
    Observable,
    of,
    skip,
    switchMap,
    take,
    timer,
} from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { escapeHtml } from '../../helpers/escape-html';
import { copyableValue, previewValue } from '../../helpers/persistence-value-preview';
import {
    PersistenceEntryOrdering,
    PersistenceEntrySortField,
    PersistenceTable,
    PersistenceTableEntry,
} from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';
import {
    PersistenceEntryDialogComponent,
    PersistenceEntryDialogData,
} from '../persistence-entry-dialog/persistence-entry-dialog.component';

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;
// Column key -> the server's ordering field. Columns not listed (Value, Actions) are not sortable.
const SORT_FIELDS: Partial<Record<string, PersistenceEntrySortField>> = {
    key: 'key',
    session_label: 'session',
    updated_at: 'updated_at',
};

// "<Flow name>, Session #<id>"; null for hand-edited entries, which no run touched.
function sessionLabel(entry: PersistenceTableEntry): string | null {
    if (entry.updated_by_session === null || entry.updated_by_graph === null) return null;
    const session = `Session #${entry.updated_by_session}`;
    return entry.updated_by_graph_name ? `${entry.updated_by_graph_name}, ${session}` : session;
}

// Trimmed term to query with. The first value (a term already typed when the tab mounts) and a cleared term go
// out at once; typing waits until it settles, so each keystroke is not a request.
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

@Component({
    selector: 'app-persistence-entries-grid',
    imports: [
        AppTableComponent,
        AppTableCellDirective,
        ButtonComponent,
        CopyButtonComponent,
        PaginationControlsComponent,
        RouterLink,
        DatePipe,
    ],
    templateUrl: './persistence-entries-grid.component.html',
    styleUrls: ['./persistence-entries-grid.component.scss'],
})
export class PersistenceEntriesGridComponent {
    readonly table = input.required<PersistenceTable>();
    // Raw text of the Files page header search; filters keys server-side once it settles.
    readonly searchTerm = input('');
    readonly canCreate = input(false);
    readonly canUpdate = input(false);
    readonly canDelete = input(false);

    readonly changed = output<void>();

    readonly search = toSignal(settledSearch(toObservable(this.searchTerm)), { initialValue: '' });
    // The id, not the table object: a refreshed tables list (new entry_count) must not re-fetch or reset paging.
    readonly tableId = computed(() => this.table().id);
    // Server-side sort, clicked from the Key / Session / Updated headers; kept across a table switch.
    readonly ordering = signal<PersistenceEntryOrdering>('key');
    // Back to page 1 whenever the table, search or sort changes; the pagination controls set it otherwise.
    readonly page = linkedSignal(() => {
        this.tableId();
        this.search();
        this.ordering();
        return 1;
    });
    // Reset on a table switch, so the old table's rows (and their entry ids) never sit under the new heading.
    readonly entries = linkedSignal<number, PersistenceTableEntry[]>({ source: this.tableId, computation: () => [] });
    readonly totalCount = linkedSignal({ source: this.tableId, computation: () => 0 });
    readonly loading = signal(false);
    readonly rows = computed<TableRow[]>(() =>
        this.entries().map((entry) => ({
            ...entry,
            preview: previewValue(entry.value),
            copy_text: copyableValue(entry.value),
            session_label: sessionLabel(entry),
        }))
    );
    readonly columns = computed<AppTableColumnDef[]>(() => {
        const actions: AppTableRowAction[] = [];
        if (this.canUpdate()) {
            actions.push({ icon: 'edit', tooltip: 'Edit entry', onClick: (row) => this.onEdit(row) });
        }
        if (this.canDelete()) {
            actions.push({
                icon: 'trash',
                tooltip: 'Delete entry',
                variant: 'danger',
                onClick: (row) => this.onDelete(row),
            });
        }
        const columns: AppTableColumnDef[] = [
            this.sortableColumn({ key: 'key', label: 'Key', width: '1fr' }),
            { key: 'preview', label: 'Value', width: '2fr' },
            this.sortableColumn({ key: 'session_label', label: 'Session', width: '1fr' }),
            this.sortableColumn({ key: 'updated_at', label: 'Updated', width: '180px' }),
        ];
        if (actions.length) {
            columns.push({ key: 'actions', label: 'Actions', width: '96px', align: 'end', actions });
        }
        return columns;
    });

    readonly loadEntries = effect((onCleanup) => {
        const page = this.page();
        this.reloadTick();
        this.loading.set(true);
        const subscription = this.persistenceTablesApi
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
                    this.entries.set(response.results);
                    this.totalCount.set(response.count);
                    this.loading.set(false);
                },
                error: (error: HttpErrorResponse) => {
                    this.loading.set(false);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
        // Cancels a stale request when the table, search or page changes before it answers.
        onCleanup(() => subscription.unsubscribe());
    });

    readonly pageSize = PAGE_SIZE;
    protected readonly dateFormat = DATE_TIME_FORMAT_24H;

    private readonly reloadTick = signal(0);
    private readonly persistenceTablesApi = inject(PersistenceTablesApiService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    onAdd(): void {
        this.openEntryDialog({ tableId: this.tableId() });
    }

    // A new column sorts ascending; clicking the sorted column flips its direction.
    onSortToggle(columnKey: string): void {
        const field = SORT_FIELDS[columnKey];
        if (!field) return;
        this.ordering.update((current) => (current === field ? `-${field}` : field));
    }

    // Double-click is the mouse shortcut; keyboard users take the row's Edit action button.
    onCellDoubleClick(row: TableRow): void {
        if (!this.canUpdate()) return;
        this.onEdit(row);
    }

    // The header icon shows the sort: up/down on the sorted column, a neutral up-down arrow on the others.
    private sortableColumn(column: AppTableColumnDef): AppTableColumnDef {
        const field = SORT_FIELDS[column.key];
        const ordering = this.ordering();
        if (ordering === field) {
            return { ...column, headerIcon: 'arrow-up', headerIconActive: true, sortDirection: 'ascending' };
        }
        if (ordering === `-${field}`) {
            return { ...column, headerIcon: 'arrow-down', headerIconActive: true, sortDirection: 'descending' };
        }
        return { ...column, headerIcon: 'arrow-up-down', headerIconActive: false };
    }

    private onEdit(row: TableRow): void {
        const entry = this.entries().find((item) => item.id === row['id']);
        if (entry) this.openEntryDialog({ tableId: this.tableId(), entry });
    }

    private onDelete(row: TableRow): void {
        const key = row['key'] as string;
        this.confirmationDialogService
            .confirmDelete(escapeHtml(key))
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.persistenceTablesApi.deleteEntry(row['id'] as number)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success(`Entry "${key}" deleted`);
                    this.afterChange();
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    private openEntryDialog(data: PersistenceEntryDialogData): void {
        this.dialog
            .open<PersistenceTableEntry | null>(PersistenceEntryDialogComponent, { width: '640px', data })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((entry) => {
                if (entry) this.afterChange();
            });
    }

    private afterChange(): void {
        this.reloadTick.update((tick) => tick + 1);
        this.changed.emit();
    }
}
