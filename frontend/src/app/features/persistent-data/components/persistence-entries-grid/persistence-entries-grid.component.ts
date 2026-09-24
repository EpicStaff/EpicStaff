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
    PaginationControlsComponent,
    SearchComponent,
    TableRow,
} from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { debounceTime, distinctUntilChanged, filter, map, switchMap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { escapeHtml } from '../../helpers/escape-html';
import { previewValue } from '../../helpers/persistence-value-preview';
import { PersistenceTable, PersistenceTableEntry } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';
import {
    PersistenceEntryDialogComponent,
    PersistenceEntryDialogData,
} from '../persistence-entry-dialog/persistence-entry-dialog.component';

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;

@Component({
    selector: 'app-persistence-entries-grid',
    imports: [
        AppTableComponent,
        AppTableCellDirective,
        ButtonComponent,
        PaginationControlsComponent,
        SearchComponent,
        RouterLink,
        DatePipe,
    ],
    templateUrl: './persistence-entries-grid.component.html',
    styleUrls: ['./persistence-entries-grid.component.scss'],
})
export class PersistenceEntriesGridComponent {
    readonly table = input.required<PersistenceTable>();
    readonly canCreate = input(false);
    readonly canUpdate = input(false);
    readonly canDelete = input(false);

    readonly changed = output<void>();

    readonly searchText = signal('');
    readonly search = toSignal(
        toObservable(this.searchText).pipe(
            debounceTime(SEARCH_DEBOUNCE_MS),
            map((text) => text.trim()),
            distinctUntilChanged()
        ),
        { initialValue: '' }
    );
    // The id, not the table object: a refreshed tables list (new entry_count) must not re-fetch or reset paging.
    readonly tableId = computed(() => this.table().id);
    // Back to page 1 whenever the table or the search changes; the pagination controls set it otherwise.
    readonly page = linkedSignal(() => {
        this.tableId();
        this.search();
        return 1;
    });
    readonly entries = signal<PersistenceTableEntry[]>([]);
    readonly totalCount = signal(0);
    readonly loading = signal(false);
    readonly rows = computed<TableRow[]>(() =>
        this.entries().map((entry) => ({ ...entry, preview: previewValue(entry.value) }))
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
            { key: 'key', label: 'Key', width: '1fr' },
            { key: 'preview', label: 'Value', width: '2fr' },
            { key: 'updated_at', label: 'Updated', width: '200px' },
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

    private readonly reloadTick = signal(0);
    private readonly persistenceTablesApi = inject(PersistenceTablesApiService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    onAdd(): void {
        this.openEntryDialog({ tableId: this.tableId() });
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
