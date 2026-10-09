import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ButtonComponent, ConfirmationDialogService, TabButtonComponent } from '@shared/components';
import { HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { ActionCode } from '@shared/models';
import { filter, finalize, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsStorageService } from '../../../../services/recycle-bin';
import { RecycleBinBulkService } from '../../services/recycle-bin-bulk.service';
import { RecycleBinReloadService } from '../../services/recycle-bin-reload.service';
import {
    bulkActionErrorMessage,
    emptyRecycleBinConfirmationDialog,
    failedItemsMessage,
    purgeResultMessage,
} from '../../utils/recycle-bin-messages.util';
import { visibleRecycleBinTabs } from '../../utils/visible-recycle-bin-tabs.util';

@Component({
    selector: 'app-recycle-bin-page',
    imports: [
        RouterOutlet,
        RouterLink,
        RouterLinkActive,
        TabButtonComponent,
        ButtonComponent,
        HideInlineSubtitleOnOverflowDirective,
    ],
    templateUrl: './recycle-bin-page.component.html',
    styleUrls: ['./recycle-bin-page.component.scss'],
    providers: [RecycleBinReloadService],
})
export class RecycleBinPageComponent {
    protected readonly visibleTabs = computed(() =>
        visibleRecycleBinTabs((resource, action) => this.permissionsService.can(resource, action))
    );
    /** The tabs "Empty recycle bin" empties: every visible tab the user may delete on. */
    protected readonly purgeableTabs = computed(() =>
        this.visibleTabs().filter((tab) => this.permissionsService.can(tab.resource, ActionCode.Delete))
    );
    protected readonly subtitle = computed(() => {
        const days = this.recycleBinSettings.retentionDays();
        return days === null
            ? "Deleted items stay here for a while, then they're removed for good."
            : `Deleted items stay here for ${days} ${days === 1 ? 'day' : 'days'}, then they're removed for good.`;
    });
    protected readonly emptying = signal(false);

    private readonly permissionsService = inject(PermissionsService);
    private readonly recycleBinSettings = inject(RecycleBinSettingsStorageService);
    private readonly bulk = inject(RecycleBinBulkService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly reloadRequests = inject(RecycleBinReloadService);
    private readonly destroyRef = inject(DestroyRef);

    protected onEmptyRecycleBin(): void {
        const tabs = this.purgeableTabs();
        this.confirmationDialog
            .confirm(emptyRecycleBinConfirmationDialog(tabs))
            .pipe(
                filter((result) => result === true),
                switchMap(() => {
                    this.emptying.set(true);
                    return this.bulk
                        .purgeAll(tabs.flatMap((tab) => tab.sources))
                        .pipe(finalize(() => this.emptying.set(false)));
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (result) => {
                    const success = purgeResultMessage(result);
                    if (success !== null) this.toastService.success(success);
                    else if (result.failed.length === 0) this.toastService.success('The recycle bin is already empty.');
                    const failure = failedItemsMessage('delete', result.failed);
                    if (failure !== null) this.toastService.error(failure);
                    this.reloadRequests.request();
                },
                error: (error: HttpErrorResponse) => {
                    // A 403 is handled by the forbidden interceptor, which also reloads the page.
                    if (error.status === 403) return;
                    const message = bulkActionErrorMessage(error, 'delete');
                    if (message !== null) this.toastService.error(message);
                    this.reloadRequests.request();
                },
            });
    }
}
