import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter, finalize, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { CustomLibraryCardComponent } from '../../components/custom-library-card/custom-library-card.component';
import {
    CustomLibraryDialogComponent,
    CustomLibraryDialogData,
    CustomLibraryDialogResult,
} from '../../components/custom-library-dialog/custom-library-dialog.component';
import { CustomLibrary } from '../../models/custom-library.model';
import { VenvSortOrder } from '../../models/venv.model';
import { CustomLibrariesApiService } from '../../services/custom-libraries-api.service';

@Component({
    selector: 'app-custom-libraries-list-page',
    imports: [CustomLibraryCardComponent],
    templateUrl: './custom-libraries-list-page.component.html',
    styleUrls: ['./custom-libraries-list-page.component.scss'],
})
export class CustomLibrariesListPageComponent {
    /** Both come from the page header, which owns the tab this list sits in. The gateway takes
     *  neither, so the whole page is loaded once and narrowed and ordered here. */
    readonly searchTerm = input<string>('');
    readonly sortOrder = input<VenvSortOrder>('default');

    readonly isLoading = signal(true);
    readonly libraries = signal<CustomLibrary[]>([]);
    // A delete is on its way (confirmation, delete): a second request for any library is ignored
    // until it ends, so a double click cannot open two dialogs or send two deletes.
    readonly deletePending = signal(false);

    readonly canDelete = computed(() => this.permissions.can(ResourceCode.CustomLibraries, ActionCode.Delete));

    /** The libraries as the page shows them: narrowed by the search, then ordered. A library a
     *  build has not named yet matches nothing and sorts last, having no name to sort by. */
    readonly visibleLibraries = computed(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const matching = term
            ? this.libraries().filter((library) => (library.name ?? '').toLowerCase().includes(term))
            : this.libraries();
        return this.ordered(matching);
    });

    private readonly customLibrariesApi = inject(CustomLibrariesApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        this.loadLibraries();
    }

    /** Called by the page that owns the tab, where the create button lives. */
    openCreateDialog(): void {
        this.dialog
            // disableClose: a stray backdrop click must not throw away a half-filled wheel list.
            .open<CustomLibraryDialogResult>(CustomLibraryDialogComponent, { disableClose: true })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (!result) return;
                if (result !== 'changed') {
                    // `name` is null when a source archive created it: nothing has named it yet.
                    this.toastService.success(
                        result.name ? `Custom library "${result.name}" created` : 'Custom library created'
                    );
                }
                this.loadLibraries();
            });
    }

    onOpen(library: CustomLibrary): void {
        this.dialog
            .open<CustomLibraryDialogResult, CustomLibraryDialogData>(CustomLibraryDialogComponent, {
                disableClose: true,
                data: { library },
            })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                // Only versions can change here, and the row shows none of them; the list is
                // reloaded all the same, so a library deleted elsewhere does not linger.
                if (result) this.loadLibraries();
            });
    }

    onDelete(library: CustomLibrary): void {
        if (this.deletePending()) return;
        this.deletePending.set(true);
        // `confirmDelete` emits `false`/completes when cancelled, so `finalize` is what clears the
        // pending flag on both the delete and the dismissed-dialog paths.
        this.confirmationDialogService
            .confirmDelete(library.name ?? 'this library')
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.customLibrariesApi.deleteCustomLibrary(library.id)),
                finalize(() => this.deletePending.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success(
                        library.name ? `Custom library "${library.name}" deleted` : 'Custom library deleted'
                    );
                    this.loadLibraries();
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    private ordered(libraries: CustomLibrary[]): CustomLibrary[] {
        const order = this.sortOrder();
        if (order === 'default') return libraries;
        const direction = order === 'name_asc' ? 1 : -1;
        return [...libraries].sort((left, right) => {
            if (left.name === null) return 1;
            if (right.name === null) return -1;
            return left.name.localeCompare(right.name) * direction;
        });
    }

    private loadLibraries(): void {
        this.customLibrariesApi
            .getCustomLibraries()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (libraries) => {
                    this.libraries.set(libraries);
                    this.isLoading.set(false);
                },
                error: (error: HttpErrorResponse) => {
                    this.isLoading.set(false);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }
}
