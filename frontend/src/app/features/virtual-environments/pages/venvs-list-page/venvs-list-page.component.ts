import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, ConfirmationDialogService, SearchComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import { filter, finalize, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { VenvCardComponent } from '../../components/venv-card/venv-card.component';
import { VenvDialogComponent, VenvDialogData } from '../../components/venv-dialog/venv-dialog.component';
import { Venv } from '../../models/venv.model';
import { VenvsApiService } from '../../services/venvs-api.service';

@Component({
    selector: 'app-venvs-list-page',
    imports: [ButtonComponent, SearchComponent, HasPermissionDirective, VenvCardComponent],
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

    readonly filteredVenvs = computed<Venv[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const venvs = this.venvs();
        if (!term) return venvs;
        return venvs.filter((venv) => venv.name.toLowerCase().includes(term));
    });

    readonly canUpdate = computed(() => this.permissions.can(ResourceCode.Venvs, ActionCode.Update));
    readonly canDelete = computed(() => this.permissions.can(ResourceCode.Venvs, ActionCode.Delete));

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    private readonly venvsApi = inject(VenvsApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        this.loadVenvs();
    }

    onCreate(): void {
        this.dialog
            // disableClose: the Operator `app-select` opens a CDK overlay with its own
            // backdrop; without this the dialog closes the moment that dropdown is clicked.
            // The dialog closes only via Cancel/X/submit, which call dialogRef.close().
            .open<Venv | null>(VenvDialogComponent, { width: '640px', disableClose: true })
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
                width: '640px',
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
