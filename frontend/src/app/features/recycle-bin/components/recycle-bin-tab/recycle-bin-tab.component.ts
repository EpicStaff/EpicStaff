import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, input, linkedSignal, OnInit, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import {
    ButtonComponent,
    ConfirmationDialogData,
    ConfirmationDialogService,
    SearchComponent,
} from '@shared/components';
import { ActionCode } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import {
    debounceTime,
    defer,
    distinctUntilChanged,
    filter,
    finalize,
    Observable,
    skip,
    Subject,
    Subscription,
    switchMap,
} from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
import { RECYCLE_BIN_TAB_BY_KEY } from '../../constants/recycle-bin-tabs.constants';
import {
    RecycleBinItem,
    RecycleBinPurgeResult,
    RecycleBinRestoreResult,
    RecycleBinSort,
    RecycleBinSortField,
    RecycleBinTabKey,
} from '../../models/recycle-bin.model';
import { RecycleBinBulkService } from '../../services/recycle-bin-bulk.service';
import { RecycleBinReloadService } from '../../services/recycle-bin-reload.service';
import { RecycleBinStorageService } from '../../services/recycle-bin-storage.service';
import {
    bulkActionErrorMessage,
    failedItemsMessage,
    purgeConfirmationDialog,
    purgeResultMessage,
    purgeSelectedConfirmationDialog,
    RecycleBinAction,
    recycleBinActionErrorMessage,
    restoreResultMessage,
} from '../../utils/recycle-bin-messages.util';
import {
    DEFAULT_SORT,
    flipColumnDirection,
    hasKindSwitch,
    INITIAL_COLUMN_DIRECTIONS,
    initialKindFilter,
    kindFilterNarrows,
    kindFilterOptions,
    shownSource,
    toListQuery,
} from '../../utils/recycle-bin-query.util';
import { isExpandableItem } from '../../utils/recycle-bin-rows.util';
import { recycleBinTabShowsKind } from '../../utils/visible-recycle-bin-tabs.util';
import { RecycleBinTableComponent } from '../recycle-bin-table/recycle-bin-table.component';

/** How long typing pauses before the list asks the server again. */
const SERVER_SEARCH_DEBOUNCE_MS = 300;

/**
 * How long the restore toast stays. It shows its whole text, which can list renames the user has to act on,
 * so it stays longer than the default success toast.
 */
const RESTORE_TOAST_DURATION_MS = 10_000;

/**
 * One bin tab. Every route tab gets its own instance (and its own storage service), so switching
 * tabs starts from an empty list. Every action reloads the list and clears the selection: a
 * restore can bring back parent folders or owned surfaces, and a folder purge can take other
 * rows with it.
 *
 * The list is paged, searched, sorted and filtered on the server. A tab with two bins (Tools) shows one
 * at a time, picked by its Kind switch. Bulk actions apply to the selected rows of the page shown;
 * emptying everything is the page's "Empty recycle bin".
 */
@Component({
    selector: 'app-recycle-bin-tab',
    imports: [RecycleBinTableComponent, SearchComponent, ButtonComponent],
    templateUrl: './recycle-bin-tab.component.html',
    styleUrls: ['./recycle-bin-tab.component.scss'],
    providers: [RecycleBinStorageService],
})
export class RecycleBinTabComponent implements OnInit {
    readonly recycleBinTab = input.required<RecycleBinTabKey>();

    // Declared above the state on purpose: the fields below read their signals while the class initializes.
    private readonly storage = inject(RecycleBinStorageService);
    private readonly recycleBinSettings = inject(RecycleBinSettingsService);
    /** Absent outside the page (the tab's own specs). */
    private readonly reloadRequests = inject(RecycleBinReloadService, { optional: true });

    private readonly table = viewChild(RecycleBinTableComponent);

    protected readonly tab = computed(() => RECYCLE_BIN_TAB_BY_KEY[this.recycleBinTab()]);
    protected readonly showKind = computed(() => recycleBinTabShowsKind(this.tab()));
    protected readonly countLabel = computed(() => this.tab().countColumn?.label ?? null);
    protected readonly canRestore = computed(() => this.permissionsService.can(this.tab().resource, ActionCode.Create));
    /**
     * Deleting forever is superadmin-only on the server, whatever the role's DELETE grants. Superadmin is a
     * global flag (an org switch never changes it); the getter reads a signal, so this follows the /me
     * reload after a 403 and logout's clear().
     */
    protected readonly canPurge = computed(() => this.permissionsService.isSuperadmin);
    /** No checkboxes when there is nothing the user could do with a selection. */
    protected readonly selectable = computed(() => this.canRestore() || this.canPurge());
    protected readonly searchTerm = signal('');
    /** Each date column's own direction (its arrow), and the column the list is sorted by. */
    protected readonly columnDirections = signal(INITIAL_COLUMN_DIRECTIONS);
    protected readonly sortField = signal<RecycleBinSortField>(DEFAULT_SORT.field);
    protected readonly sort = computed<RecycleBinSort>(() => ({
        field: this.sortField(),
        direction: this.columnDirections()[this.sortField()],
    }));
    /** Options of the Kind column's filter (Tools: the tool sources, Files: file / folder). */
    protected readonly kindOptions = computed(() => kindFilterOptions(this.tab()));
    /** Tools: the Kind filter picks which bin is listed, so one is always chosen. */
    protected readonly kindSwitch = computed(() => hasKindSwitch(this.tab()));
    /** Files: an item type, or `null` for both. Tools: the source shown (see kindSwitch). */
    protected readonly kindFilter = linkedSignal<string | null>(() => initialKindFilter(this.tab()));
    /** The count column's filter (Flows, Agents…): a COUNT_FILTER_OPTIONS value, or `null` for all. */
    protected readonly countFilter = signal<string | null>(null);
    /** A search or filter narrows the list; the Kind switch doesn't, it picks the list. */
    protected readonly filtered = computed(
        () =>
            this.searchTerm().trim() !== '' ||
            kindFilterNarrows(this.kindFilter(), this.kindSwitch()) ||
            this.countFilter() !== null
    );
    /**
     * The search shows once there's something to search, and stays while a search or filter is active so
     * it can be undone. Not while the first load runs or for an empty bin; a reload keeps the items shown.
     */
    protected readonly showSearch = computed(() => this.filtered() || this.storage.items().length > 0);
    /** Rows open in the table (shared with it), and the rows that have something to open. */
    protected readonly expandedKeys = signal<ReadonlySet<string>>(new Set());
    protected readonly expandableKeys = computed(() =>
        this.items()
            .filter(isExpandableItem)
            .map((item) => item.key)
    );
    protected readonly allExpanded = computed(() => {
        const keys = this.expandableKeys();
        return keys.length > 0 && keys.every((key) => this.expandedKeys().has(key));
    });
    protected readonly items = this.storage.items;
    protected readonly status = this.storage.status;
    protected readonly page = this.storage.page;
    protected readonly retentionDays = this.recycleBinSettings.retentionDays;
    protected readonly pendingKeys = signal<ReadonlySet<string>>(new Set());
    /** Rows whose "Show all" is loading. */
    protected readonly loadingContentKeys = signal<ReadonlySet<string>>(new Set());
    protected readonly selectedKeys = signal<ReadonlySet<string>>(new Set());
    protected readonly selectedItems = computed(() => this.items().filter((item) => this.selectedKeys().has(item.key)));
    protected readonly selectedCount = computed(() => this.selectedItems().length);
    protected readonly restoreSelectedLabel = computed(() => `Restore (${this.selectedCount()})`);
    protected readonly deleteSelectedLabel = computed(() => `Delete (${this.selectedCount()})`);
    protected readonly bulkBusy = signal(false);

    private readonly permissionsService = inject(PermissionsService);
    private readonly bulk = inject(RecycleBinBulkService);
    private readonly toastService = inject(ToastService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly secretsStorage = inject(SecretsStorageService);
    private readonly serverSearches = new Subject<string>();
    private loadSubscription: Subscription | null = null;

    constructor() {
        this.serverSearches
            .pipe(debounceTime(SERVER_SEARCH_DEBOUNCE_MS), distinctUntilChanged(), takeUntilDestroyed())
            .subscribe(() => this.reload(1));
        if (this.reloadRequests) {
            // The first value is the current count; only later requests (the page's "Empty recycle bin") reload.
            toObservable(this.reloadRequests.requests)
                .pipe(skip(1), takeUntilDestroyed())
                .subscribe(() => {
                    this.reload();
                    this.refreshSecretPickers();
                });
        }
    }

    ngOnInit(): void {
        this.reload();
    }

    protected onSearch(term: string): void {
        this.searchTerm.set(term);
        this.clearSelection();
        this.serverSearches.next(term.trim());
    }

    /** Picking the option already chosen changes nothing, so it keeps the page and selection. */
    protected onKindFilterChanged(value: string | null): void {
        if (value === this.kindFilter()) return;
        this.kindFilter.set(value);
        this.reload(1);
    }

    protected onCountFilterChanged(value: string | null): void {
        if (value === this.countFilter()) return;
        this.countFilter.set(value);
        this.reload(1);
    }

    protected onSort(field: RecycleBinSortField): void {
        this.columnDirections.update((directions) => flipColumnDirection(directions, field));
        this.sortField.set(field);
        this.reload(1);
    }

    /**
     * Loads every content of a row whose list was capped (up to the "Show all" limit). A reload after an
     * action brings back the capped list; "Show all" loads it again.
     */
    protected onShowAll(item: RecycleBinItem): void {
        if (this.loadingContentKeys().has(item.key)) return;
        this.loadingContentKeys.update((keys) => new Set(keys).add(item.key));
        this.storage
            .loadAllContents(item)
            .pipe(
                finalize(() =>
                    this.loadingContentKeys.update((keys) => {
                        const next = new Set(keys);
                        next.delete(item.key);
                        return next;
                    })
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                error: (error: HttpErrorResponse) => {
                    // A 404: it was restored or deleted meanwhile; a reload shows that.
                    if (error.status === 404) this.reload();
                    else this.toastService.error(`Couldn't load everything inside "${item.displayName}".`);
                },
            });
    }

    /** Opens every row shown, or closes them all when they're all open. */
    protected onToggleAllExpanded(): void {
        this.expandedKeys.set(this.allExpanded() ? new Set() : new Set(this.expandableKeys()));
    }

    protected onSelectionToggled(item: RecycleBinItem): void {
        this.selectedKeys.update((keys) => {
            const next = new Set(keys);
            if (next.has(item.key)) next.delete(item.key);
            else next.add(item.key);
            return next;
        });
    }

    /** Selects or clears every row shown (the current page, after the search). */
    protected onAllToggled(checked: boolean): void {
        this.selectedKeys.set(checked ? new Set(this.items().map((item) => item.key)) : new Set());
    }

    protected onRestore(item: RecycleBinItem): void {
        // No confirmation: a restore is undone by deleting the item again.
        this.runRowAction(item, this.bulk.restoreItems([item]))
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => this.onRestored(result),
                error: (error: HttpErrorResponse) => this.onActionError(error, 'restore', item),
            });
    }

    protected onPurge(item: RecycleBinItem): void {
        this.confirmThen(purgeConfirmationDialog(item), () => this.runRowAction(item, this.bulk.purgeItems([item])))
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => this.onPurged(result, item.name),
                error: (error: HttpErrorResponse) => this.onActionError(error, 'delete', item),
            });
    }

    protected onRestoreSelected(): void {
        const items = this.selectedItems();
        this.runBulk(null, () => this.bulk.restoreItems(items), 'restore');
    }

    protected onDeleteSelected(): void {
        const items = this.selectedItems();
        const dialog = purgeSelectedConfirmationDialog(items.map((item) => item.name));
        this.runBulk(dialog, () => this.bulk.purgeItems(items), 'delete');
    }

    protected onRetry(): void {
        this.reload();
    }

    protected onPageRequested(pageNumber: number): void {
        this.reload(pageNumber);
    }

    /** Opens `dialog` and runs `action` only when the user confirms; without a dialog it just runs. */
    private confirmThen<T>(dialog: ConfirmationDialogData | null, action: () => Observable<T>): Observable<T> {
        if (dialog === null) return defer(action);
        return this.confirmationDialog.confirm(dialog).pipe(
            filter((result) => result === true),
            switchMap(action)
        );
    }

    /** Marks the row busy (no double submit) while `action$` runs. */
    private runRowAction<T>(item: RecycleBinItem, action$: Observable<T>): Observable<T> {
        this.setPending(item.key, true);
        // Its button is disabled while pending and goes with the row: the table moves the focus on.
        this.table()?.focusRowAfterReload(this.items().findIndex((shown) => shown.key === item.key));
        return action$.pipe(finalize(() => this.setPending(item.key, false)));
    }

    /** A toolbar action: confirm (unless `dialog` is null), run with the toolbar busy, then toast the result and reload. */
    private runBulk(
        dialog: ConfirmationDialogData | null,
        action: () => Observable<RecycleBinRestoreResult | RecycleBinPurgeResult>,
        kind: RecycleBinAction
    ): void {
        this.confirmThen(dialog, () => {
            this.bulkBusy.set(true);
            // The toolbar's buttons go with the selection the reload clears: the focus moves to the first row.
            this.table()?.focusRowAfterReload(0);
            return action().pipe(finalize(() => this.bulkBusy.set(false)));
        })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => ('restored' in result ? this.onRestored(result) : this.onPurged(result, undefined)),
                error: (error: HttpErrorResponse) => {
                    // A 403 is handled by the forbidden interceptor (see onActionError).
                    if (error.status === 403) return;
                    const message = bulkActionErrorMessage(error, kind);
                    if (message !== null) this.toastService.error(message);
                    this.reload();
                },
            });
    }

    private onRestored(result: RecycleBinRestoreResult): void {
        const success = restoreResultMessage(result);
        if (success !== null) {
            this.toastService.success(success, RESTORE_TOAST_DURATION_MS, undefined, { fullText: true });
        }
        const failure = failedItemsMessage('restore', result.failed);
        if (failure !== null) this.toastService.error(failure);
        this.reload();
        if (this.tab().sources.includes('secret')) this.refreshSecretPickers();
    }

    private onPurged(result: RecycleBinPurgeResult, itemName: string | undefined): void {
        const success = purgeResultMessage(result, itemName);
        if (success !== null) this.toastService.success(success);
        const failure = failedItemsMessage('delete', result.failed);
        if (failure !== null) this.toastService.error(failure);
        this.reload();
        if (this.tab().sources.includes('secret')) this.refreshSecretPickers();
    }

    /** Secret pickers name binned secrets from a cached list; a restore or purge here changes it. */
    private refreshSecretPickers(): void {
        this.secretsStorage
            .getSecrets(true)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => undefined });
    }

    private onActionError(error: HttpErrorResponse, action: RecycleBinAction, item: RecycleBinItem): void {
        // The forbidden interceptor already toasted the server's message, refreshed the
        // permissions and remounted the page, so there's nothing left to do here.
        if (error.status === 403) return;
        const message = recycleBinActionErrorMessage(error, action, item.name);
        if (message !== null) this.toastService.error(message);
        // A 404 means someone else already restored or purged it; a reload shows that.
        this.reload();
    }

    /** Loads page `pageNumber` (by default the page shown) of the bin shown, and clears the selection. */
    private reload(pageNumber?: number): void {
        this.clearSelection();
        // A newer load (a page click, a search, a reload after an action) replaces one still in flight.
        this.loadSubscription?.unsubscribe();
        this.loadSubscription = this.storage
            .load(shownSource(this.tab(), this.kindFilter()), {
                page: pageNumber,
                query: toListQuery(this.searchTerm(), this.sort(), this.kindFilter(), this.countFilter()),
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            // The storage service already set the 'error' status the table shows.
            .subscribe({ error: () => undefined });
    }

    private clearSelection(): void {
        if (this.selectedKeys().size > 0) this.selectedKeys.set(new Set());
    }

    private setPending(key: string, pending: boolean): void {
        this.pendingKeys.update((keys) => {
            const next = new Set(keys);
            if (pending) next.add(key);
            else next.delete(key);
            return next;
        });
    }
}
