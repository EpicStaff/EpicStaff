import { Dialog } from '@angular/cdk/dialog';
import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
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
import { filter, finalize, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { VenvCardComponent } from '../../components/venv-card/venv-card.component';
import { VenvDialogComponent, VenvDialogData } from '../../components/venv-dialog/venv-dialog.component';
import { Venv } from '../../models/venv.model';
import { VenvsApiService } from '../../services/venvs-api.service';

type VenvSortOrder = 'default' | 'name_asc' | 'name_desc';

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
    ],
    templateUrl: './venvs-list-page.component.html',
    styleUrls: ['./venvs-list-page.component.scss'],
})
export class VenvsListPageComponent {
    readonly isLoading = signal(true);
    readonly loadError = signal<string | null>(null);
    readonly venvs = signal<Venv[]>([]);
    readonly searchTerm = signal('');
    // A delete is on its way (confirmation, delete): a second request for any venv is ignored
    // until it ends, so a double click cannot open two dialogs or send two deletes.
    readonly deletePending = signal(false);

    readonly sortOrder = signal<VenvSortOrder>('default');
    readonly filterMenuOpen = signal(false);

    readonly filteredVenvs = computed<Venv[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const venvs = term ? this.venvs().filter((venv) => venv.name.toLowerCase().includes(term)) : this.venvs();
        const sortOrder = this.sortOrder();
        if (sortOrder === 'default') return venvs;
        const direction = sortOrder === 'name_asc' ? 1 : -1;
        return [...venvs].sort((a, b) => direction * a.name.localeCompare(b.name));
    });
    readonly hasActiveFilter = computed(() => this.sortOrder() !== 'default');

    readonly canUpdate = computed(() => this.permissions.can(ResourceCode.Venvs, ActionCode.Update));
    readonly canDelete = computed(() => this.permissions.can(ResourceCode.Venvs, ActionCode.Delete));

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
    protected readonly filterMenuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top' },
    ];

    private readonly venvsApi = inject(VenvsApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        this.loadVenvs();
    }

    toggleFilterMenu(): void {
        this.filterMenuOpen.update((open) => !open);
    }

    closeFilterMenu(): void {
        this.filterMenuOpen.set(false);
    }

    applySort(sortOrder: VenvSortOrder): void {
        this.sortOrder.set(sortOrder);
        this.closeFilterMenu();
    }

    clearAllFilters(): void {
        this.sortOrder.set('default');
    }

    onCreate(): void {
        this.dialog
            // disableClose: the Specification `app-select` overlay has its own backdrop; a click on it
            // would otherwise close the dialog.
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
                    this.loadVenvs();
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    private loadVenvs(): void {
        this.isLoading.set(true);
        this.loadError.set(null);
        this.venvsApi
            .getVenvs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (venvs) => {
                    this.venvs.set(venvs);
                    this.isLoading.set(false);
                },
                error: (error: HttpErrorResponse) => {
                    this.isLoading.set(false);
                    this.loadError.set(extractHttpErrorMessage(error));
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }
}
