import { Dialog } from '@angular/cdk/dialog';
import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    inject,
    Injector,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    SearchComponent,
    TabButtonComponent,
} from '@shared/components';
import { HasPermissionDirective, HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import {
    catchError,
    debounceTime,
    distinctUntilChanged,
    EMPTY,
    filter,
    finalize,
    map,
    repeat,
    skip,
    Subscription,
    switchMap,
    timer,
} from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { VenvCardComponent } from '../../components/venv-card/venv-card.component';
import { VenvDialogComponent, VenvDialogData } from '../../components/venv-dialog/venv-dialog.component';
import { BUILDING_STATUSES, Venv, VenvListQuery, VenvSortOrder } from '../../models/venv.model';
import { VenvsApiService } from '../../services/venvs-api.service';
import { VenvsFilterMenuComponent, VenvsFilterState } from './components/venvs-filter-menu/venvs-filter-menu.component';
import { VENVS_SORT_MENU_ITEMS, VenvsSortMenuComponent } from './components/venvs-sort-menu/venvs-sort-menu.component';

const POLL_INTERVAL_MS = 2_000;
// Long enough that typing a word is one request, short enough to feel immediate.
const SEARCH_DEBOUNCE_MS = 300;

@Component({
    selector: 'app-venvs-list-page',
    imports: [
        OverlayModule,
        MatTooltipModule,
        AppSvgIconComponent,
        ButtonComponent,
        SearchComponent,
        TabButtonComponent,
        HasPermissionDirective,
        HideInlineSubtitleOnOverflowDirective,
        VenvCardComponent,
        VenvsFilterMenuComponent,
        VenvsSortMenuComponent,
    ],
    templateUrl: './venvs-list-page.component.html',
    styleUrls: ['./venvs-list-page.component.scss'],
})
export class VenvsListPageComponent {
    private readonly venvCards = viewChildren(VenvCardComponent);
    private readonly createButton = viewChild('createButton', { read: ButtonComponent });

    readonly isLoading = signal(true);
    readonly loadError = signal<string | null>(null);
    readonly venvs = signal<Venv[]>([]);
    readonly searchTerm = signal('');
    // A delete is on its way (confirmation, delete): a second request for any venv is ignored
    // until it ends, so a double click cannot open two dialogs or send two deletes.
    readonly deletePending = signal(false);

    readonly sortOrder = signal<VenvSortOrder>('default');
    readonly favoritesOnly = signal(false);
    readonly filterMenuOpen = signal(false);
    readonly sortMenuOpen = signal(false);

    // What the backend is asked for: it does the filtering and the sorting, the page only
    // renders what comes back.
    readonly queryParams = computed<VenvListQuery>(() => ({
        search: this.searchTerm().trim(),
        order: this.sortOrder(),
        isFavorite: this.favoritesOnly(),
    }));
    readonly filterState = computed<VenvsFilterState>(() => ({ favoritesOnly: this.favoritesOnly() }));
    readonly activeFilterCount = computed(() => (this.favoritesOnly() ? 1 : 0));
    readonly sortTriggerLabel = computed(() => {
        const order = this.sortOrder();
        if (order === 'default') return 'Sort';
        return VENVS_SORT_MENU_ITEMS.find((item) => item.value === order)?.label ?? 'Sort';
    });

    readonly canUpdate = computed(() => this.permissions.can(ResourceCode.Venvs, ActionCode.Update));
    readonly canDelete = computed(() => this.permissions.can(ResourceCode.Venvs, ActionCode.Delete));

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top' },
    ];

    private readonly venvsApi = inject(VenvsApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    private pollSubscription: Subscription | null = null;
    // Dropped before the next request is sent, so a slow answer to an old search cannot
    // land after a newer one and put the wrong list on screen.
    private listSubscription: Subscription | null = null;

    constructor() {
        this.loadVenvs();
        // Typing reloads the list; a sort does so from `applySort`, which needs no debounce.
        toObservable(this.searchTerm)
            .pipe(
                skip(1),
                map((term) => term.trim()),
                debounceTime(SEARCH_DEBOUNCE_MS),
                distinctUntilChanged(),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.loadVenvs());
    }

    toggleFilterMenu(): void {
        this.filterMenuOpen.update((open) => !open);
    }

    closeFilterMenu(): void {
        this.filterMenuOpen.set(false);
    }

    toggleSortMenu(): void {
        this.sortMenuOpen.update((open) => !open);
    }

    closeSortMenu(): void {
        this.sortMenuOpen.set(false);
    }

    onSortSelected(sortOrder: VenvSortOrder): void {
        this.sortOrder.set(sortOrder);
        this.closeSortMenu();
        this.loadVenvs();
    }

    /** The filter panel edits a draft, so nothing is narrowed until it is saved. */
    onFilterSave(filter: VenvsFilterState): void {
        this.closeFilterMenu();
        this.favoritesOnly.set(filter.favoritesOnly);
        this.loadVenvs();
    }

    onFilterClear(): void {
        this.closeFilterMenu();
        this.clearAllFilters();
    }

    // Also reachable from the trigger itself, where the click must not open the panel.
    clearAllFilters(event?: MouseEvent): void {
        event?.stopPropagation();
        this.favoritesOnly.set(false);
        this.loadVenvs();
    }

    onFavoriteChange(venv: Venv, favorite: boolean): void {
        // The star answers the click, not the request: the list is not reloaded, so a venv
        // unstarred under "Favorites only" keeps its place until the page loads again.
        this.setFavoriteLocally(venv.id, favorite);
        this.venvsApi
            .setFavorite(venv.id, favorite)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: (error: HttpErrorResponse) => {
                    this.setFavoriteLocally(venv.id, !favorite);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }

    onCreate(): void {
        this.dialog
            // disableClose: a stray backdrop click must not throw away a half-filled library table.
            .open<Venv | null>(VenvDialogComponent, { disableClose: true })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((venv) => {
                if (!venv) return;
                this.toastService.success(`Venv "${venv.name}" created`);
                this.loadVenvs();
            });
    }

    onEdit(venv: Venv): void {
        this.dialog
            .open<Venv | null, VenvDialogData>(VenvDialogComponent, {
                disableClose: true,
                data: { venv },
            })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((updated) => {
                if (!updated) return;
                this.toastService.success(`Venv "${updated.name}" updated`);
                this.loadVenvs();
            });
    }

    onDelete(venv: Venv): void {
        if (this.deletePending()) return;
        this.deletePending.set(true);
        // `confirmDelete` emits `false`/completes when cancelled, so `finalize` is what clears the
        // pending flag on both the delete and the dismissed-dialog paths.
        this.confirmationDialogService
            .confirmDelete(escapeHtml(venv.name))
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.venvsApi.deleteVenv(venv.id)),
                finalize(() => this.deletePending.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success(`Venv "${venv.name}" deleted`);
                    const index = this.venvs().findIndex((item) => item.id === venv.id);
                    this.venvs.update((venvs) => venvs.filter((item) => item.id !== venv.id));
                    this.keepFocusAfterRemoval(index);
                    this.loadVenvs();
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    private loadVenvs(): void {
        this.stopPolling();
        this.loadError.set(null);
        // `isLoading` is the first load only: a skeleton on every keystroke would hide the
        // list the search is meant to narrow.
        this.listSubscription?.unsubscribe();
        this.listSubscription = this.venvsApi
            .getVenvs(this.queryParams())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (venvs) => {
                    this.applyVenvs(venvs);
                    this.isLoading.set(false);
                },
                error: (error: HttpErrorResponse) => {
                    this.isLoading.set(false);
                    this.loadError.set(extractHttpErrorMessage(error));
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }

    /** The deleted card takes its focused Delete button along: the focus moves to the card now in its place. */
    private keepFocusAfterRemoval(index: number): void {
        if (index === -1) return;
        afterNextRender(
            () => {
                const cards = this.venvCards();
                if (cards.length) cards[Math.min(index, cards.length - 1)].focus();
                else this.createButton()?.focus();
            },
            { injector: this.injector }
        );
    }

    private setFavoriteLocally(id: number, favorite: boolean): void {
        this.venvs.update((venvs) => venvs.map((venv) => (venv.id === id ? { ...venv, is_favorite: favorite } : venv)));
    }

    private applyVenvs(venvs: Venv[]): void {
        const previousStatuses = new Map(this.venvs().map((venv) => [venv.id, venv.status]));
        for (const venv of venvs) {
            const previousStatus = previousStatuses.get(venv.id);
            if (!previousStatus || !BUILDING_STATUSES.has(previousStatus)) continue;
            if (venv.status === 'completed') {
                this.toastService.success(`Venv "${venv.name}" is ready`);
            } else if (venv.status === 'failed') {
                this.toastService.error(`Venv "${venv.name}" failed to build`);
            }
        }

        this.venvs.set(venvs);
        if (venvs.some((venv) => BUILDING_STATUSES.has(venv.status))) {
            this.startPolling();
        } else {
            this.stopPolling();
        }
    }

    private startPolling(): void {
        if (this.pollSubscription) return;
        // timer + repeat: the next request is scheduled only after the previous response arrived.
        this.pollSubscription = timer(POLL_INTERVAL_MS)
            .pipe(
                filter(() => document.visibilityState === 'visible'),
                switchMap(() => this.venvsApi.getVenvs(this.queryParams()).pipe(catchError(() => EMPTY))),
                repeat(),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((venvs) => this.applyVenvs(venvs));
    }

    private stopPolling(): void {
        this.pollSubscription?.unsubscribe();
        this.pollSubscription = null;
    }
}
