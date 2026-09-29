import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { KeyValueEntriesGridComponent } from '../../components/key-value-entries-grid/key-value-entries-grid.component';
import {
    KeyValueTableDialogComponent,
    KeyValueTableDialogData,
} from '../../components/key-value-table-dialog/key-value-table-dialog.component';
import { KeyValueTableListComponent } from '../../components/key-value-table-list/key-value-table-list.component';
import { escapeHtml } from '../../helpers/escape-html';
import { KeyValueTable } from '../../models/key-value-table.model';
import { KeyValueTablesApiService } from '../../services/key-value-tables-api.service';
import { KeyValueTablesStorageService } from '../../services/key-value-tables-storage.service';

@Component({
    selector: 'app-key-value-tables-page',
    imports: [KeyValueTableListComponent, KeyValueEntriesGridComponent],
    templateUrl: './key-value-tables-page.component.html',
    styleUrls: ['./key-value-tables-page.component.scss'],
})
export class KeyValueTablesPageComponent {
    readonly selectedTableId = signal<number | null>(null);
    readonly selectedTable = computed(
        () => this.keyValueTablesStorage.tables().find((table) => table.id === this.selectedTableId()) ?? null
    );
    // Each action is gated on the exact verb the backend checks (rbac DEFAULT_ACTION_MAP).
    readonly canCreate = computed(() => this.permissions.can(ResourceCode.KeyValueTables, ActionCode.Create));
    readonly canUpdate = computed(() => this.permissions.can(ResourceCode.KeyValueTables, ActionCode.Update));
    readonly canDelete = computed(() => this.permissions.can(ResourceCode.KeyValueTables, ActionCode.Delete));

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
        this.confirmationDialogService
            .confirmDelete(escapeHtml(table.name))
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.keyValueTablesApi.deleteTable(table.id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success(`Table "${table.name}" deleted`);
                    this.selectedTableId.set(null);
                    this.keyValueTablesStorage.triggerRefresh();
                },
                // A 409 carries "Table is used by flows: …" in the envelope message.
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }
}
