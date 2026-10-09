import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService, ConfirmationResult } from '@shared/components';
import { STORAGE_SIDEBAR_WIDTH_KEY } from '@shared/constants';
import { ResizableSidebarDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { SidebarWidthService } from '@shared/services';
import { escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import { catchError, filter, finalize, Observable, of, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { KeyValueEntriesGridComponent } from '../../components/key-value-entries-grid/key-value-entries-grid.component';
import {
    KeyValueTableDialogComponent,
    KeyValueTableDialogData,
} from '../../components/key-value-table-dialog/key-value-table-dialog.component';
import { KeyValueTableListComponent } from '../../components/key-value-table-list/key-value-table-list.component';
import { KeyValueTable, KeyValueTableUsage } from '../../models/key-value-table.model';
import { KeyValueTablesApiService } from '../../services/key-value-tables-api.service';
import { KeyValueTablesStorageService } from '../../services/key-value-tables-storage.service';

@Component({
    selector: 'app-key-value-tables-page',
    imports: [KeyValueTableListComponent, KeyValueEntriesGridComponent, ResizableSidebarDirective],
    templateUrl: './key-value-tables-page.component.html',
    styleUrls: ['./key-value-tables-page.component.scss'],
})
export class KeyValueTablesPageComponent {
    readonly selectedTableId = signal<number | null>(null);
    // A delete is on its way (usage, confirmation, delete): a second request for any table is ignored until it ends,
    // so a double click or a held Enter cannot open two dialogs or send two deletes. The trash buttons stay enabled:
    // disabling the focused one would drop keyboard focus to <body>, where the dialog would then return it.
    readonly deletePending = signal(false);
    readonly selectedTable = computed(
        () => this.keyValueTablesStorage.tables().find((table) => table.id === this.selectedTableId()) ?? null
    );
    // Each action is gated on the exact verb the backend checks (rbac DEFAULT_ACTION_MAP).
    readonly canCreate = computed(() => this.permissions.can(ResourceCode.KeyValueTables, ActionCode.Create));
    readonly canUpdate = computed(() => this.permissions.can(ResourceCode.KeyValueTables, ActionCode.Update));
    readonly canDelete = computed(() => this.permissions.can(ResourceCode.KeyValueTables, ActionCode.Delete));

    protected readonly sidebarStorageKey = STORAGE_SIDEBAR_WIDTH_KEY;
    protected readonly sidebarWidth = inject(SidebarWidthService).getWidth(STORAGE_SIDEBAR_WIDTH_KEY);

    // Reloads rather than joining a load already in flight: on opening the page, so the page starts
    // from a fresh list, and on every refresh, which follows a change to the tables (create, rename,
    // delete, org switch) that a load already in flight may predate.
    readonly loadTablesOnRefresh = effect((onCleanup) => {
        this.keyValueTablesStorage.refreshTick();
        const subscription = this.keyValueTablesStorage.reloadTables().subscribe({
            next: (tables) => {
                // A superseded load's response never becomes the signal's value; it reaches here only
                // when it ends before this effect reruns, and must not move the selection.
                if (tables !== this.keyValueTablesStorage.tables()) return;
                // Keep the current selection while it still exists; otherwise fall back to the first table.
                const selectedId = this.selectedTableId();
                if (selectedId === null || !tables.some((table) => table.id === selectedId)) {
                    this.selectedTableId.set(tables[0]?.id ?? null);
                }
            },
            error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
        });
        // The storage drops a superseded load's late response from `tables`; unsubscribing keeps it
        // from reaching the selection fallback above too.
        onCleanup(() => subscription.unsubscribe());
    });

    readonly keyValueTablesStorage = inject(KeyValueTablesStorageService);

    private readonly keyValueTablesApi = inject(KeyValueTablesApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    onCreate(): void {
        this.dialog
            .open<KeyValueTable | null>(KeyValueTableDialogComponent, { width: '480px' })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((table) => {
                if (!table) return;
                this.toastService.success(`Table "${table.name}" created`);
                // Kept by the reload, which only falls back to the first table when the selection is gone.
                this.selectedTableId.set(table.id);
                this.keyValueTablesStorage.triggerRefresh();
            });
    }

    onRename(table: KeyValueTable): void {
        this.dialog
            .open<KeyValueTable | null, KeyValueTableDialogData>(KeyValueTableDialogComponent, {
                width: '480px',
                data: { table },
            })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((renamed) => {
                if (renamed) this.keyValueTablesStorage.triggerRefresh();
            });
    }

    onDelete(table: KeyValueTable): void {
        if (this.deletePending()) return;
        this.deletePending.set(true);
        this.keyValueTablesApi
            .getUsage(table.id)
            .pipe(
                // Deleting stays possible without the count: the dialog then says what it does without one.
                catchError(() => of(null)),
                switchMap((usage) => this.confirmTableDelete(table, usage)),
                filter((confirmed) => confirmed === true),
                switchMap(() => this.keyValueTablesApi.deleteTable(table.id)),
                finalize(() => this.deletePending.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success(`Table "${table.name}" deleted`);
                    this.selectedTableId.set(null);
                    this.keyValueTablesStorage.triggerRefresh();
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    // The backend unbinds the table from its nodes on delete, so the dialog says how many that is.
    private confirmTableDelete(table: KeyValueTable, usage: KeyValueTableUsage | null): Observable<ConfirmationResult> {
        const name = table.name;
        if (usage?.node_count === 0) return this.confirmationDialogService.confirmDelete(name);
        const usageNote = usage
            ? describeUsage(usage)
            : 'If Key-Value nodes use this table, deleting it removes the table from them, and they will need a new ' +
              'table before their flows can run.';
        return this.confirmationDialogService.confirm({
            title: 'Confirm Deletion',
            message: `Are you sure you want to delete <strong>${escapeHtml(name)}</strong>? <br> ${usageNote} <br> This action cannot be undone.`,
            confirmText: 'Delete',
            cancelText: 'Cancel',
            type: 'danger',
        });
    }
}

// Crew fails a Key-Value node with no table, so the note says what the nodes need next.
function describeUsage({ node_count, flow_count }: KeyValueTableUsage): string {
    const used = `This table is used by ${countOf(node_count, 'Key-Value node')} in ${countOf(flow_count, 'flow')}.`;
    const flows = flow_count === 1 ? 'flow' : 'flows';
    if (node_count === 1) {
        return `${used} Deleting it removes the table from that node. That node will need a new table before its flow can run.`;
    }
    return `${used} Deleting it removes the table from those nodes. Those nodes will need a new table before their ${flows} can run.`;
}

function countOf(count: number, noun: string): string {
    return `${count} ${noun}${count === 1 ? '' : 's'}`;
}
