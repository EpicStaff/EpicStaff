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
import { FilesSearchService } from '../../../files/services/files-search.service';
import { PersistenceEntriesGridComponent } from '../../components/persistence-entries-grid/persistence-entries-grid.component';
import {
    PersistenceTableDialogComponent,
    PersistenceTableDialogData,
} from '../../components/persistence-table-dialog/persistence-table-dialog.component';
import { PersistenceTableListComponent } from '../../components/persistence-table-list/persistence-table-list.component';
import { escapeHtml } from '../../helpers/escape-html';
import { PersistenceTable } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';
import { PersistenceTablesStorageService } from '../../services/persistence-tables-storage.service';

@Component({
    selector: 'app-persistent-data-page',
    imports: [PersistenceTableListComponent, PersistenceEntriesGridComponent],
    templateUrl: './persistent-data-page.component.html',
    styleUrls: ['./persistent-data-page.component.scss'],
})
export class PersistentDataPageComponent {
    readonly selectedTableId = signal<number | null>(null);
    readonly visibleTables = computed(() => {
        const term = this.filesSearchService.searchTerm().trim().toLowerCase();
        return this.persistenceTablesStorage.tables().filter((table) => table.name.toLowerCase().includes(term));
    });
    readonly selectedTable = computed(
        () => this.persistenceTablesStorage.tables().find((table) => table.id === this.selectedTableId()) ?? null
    );
    // Each action is gated on the exact verb the backend checks (rbac DEFAULT_ACTION_MAP).
    readonly canCreate = computed(() => this.permissions.can(ResourceCode.PersistentData, ActionCode.Create));
    readonly canUpdate = computed(() => this.permissions.can(ResourceCode.PersistentData, ActionCode.Update));
    readonly canDelete = computed(() => this.permissions.can(ResourceCode.PersistentData, ActionCode.Delete));

    readonly loadTablesOnRefresh = effect((onCleanup) => {
        this.persistenceTablesStorage.refreshTick();
        const subscription = this.persistenceTablesStorage.loadTables().subscribe({
            next: (tables) => {
                // Keep the current selection while it still exists; otherwise fall back to the first table.
                const selectedId = this.selectedTableId();
                if (selectedId === null || !tables.some((table) => table.id === selectedId)) {
                    this.selectedTableId.set(tables[0]?.id ?? null);
                }
            },
            error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
        });
        // A newer refresh supersedes an in-flight load, so a slow stale response can't overwrite it.
        onCleanup(() => subscription.unsubscribe());
    });

    readonly persistenceTablesStorage = inject(PersistenceTablesStorageService);

    private readonly persistenceTablesApi = inject(PersistenceTablesApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly filesSearchService = inject(FilesSearchService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    onRename(table: PersistenceTable): void {
        this.dialog
            .open<PersistenceTable | null, PersistenceTableDialogData>(PersistenceTableDialogComponent, {
                width: '480px',
                data: { table },
            })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((renamed) => {
                if (renamed) this.persistenceTablesStorage.triggerRefresh();
            });
    }

    onDelete(table: PersistenceTable): void {
        this.confirmationDialogService
            .confirmDelete(escapeHtml(table.name))
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.persistenceTablesApi.deleteTable(table.id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success(`Table "${table.name}" deleted`);
                    this.selectedTableId.set(null);
                    this.persistenceTablesStorage.triggerRefresh();
                },
                // A 409 carries "Table is used by flows: …" in the envelope message.
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }
}
