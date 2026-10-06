import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ButtonComponent,
    ConfirmationDialogService,
    DeleteButtonComponent,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml } from '@shared/utils';
import { Observable } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginDetail, PluginSummary } from '../../models/plugin.model';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { isPluginIconUrl, pluginStatusLabel } from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error.util';
import {
    PluginDeleteDialogComponent,
    PluginDeleteDialogData,
} from '../plugin-delete-dialog/plugin-delete-dialog.component';
import { PluginInstallDialogComponent } from '../plugin-install-dialog/plugin-install-dialog.component';
import {
    PluginSecretsDialogComponent,
    PluginSecretsDialogData,
} from '../plugin-secrets-dialog/plugin-secrets-dialog.component';

interface PluginRow {
    plugin: PluginSummary;
    iconUrl: string | null;
    statusLabel: string;
    statusClass: string;
    hasSecretSlots: boolean;
}

@Component({
    selector: 'app-plugins-section',
    imports: [
        ButtonComponent,
        DeleteButtonComponent,
        FetchErrorStateComponent,
        LoadingSpinnerComponent,
        HasPermissionDirective,
    ],
    templateUrl: './plugins-section.component.html',
    styleUrls: ['./plugins-section.component.scss'],
})
export class PluginsSectionComponent implements OnInit {
    protected readonly loadFailed = signal(false);
    private readonly busyIds = signal<ReadonlySet<number>>(new Set());

    protected readonly rows = computed<PluginRow[]>(() =>
        this.pluginsStore.plugins().map((plugin) => ({
            plugin,
            iconUrl: isPluginIconUrl(plugin.icon_data_url) ? plugin.icon_data_url : null,
            statusLabel: pluginStatusLabel(plugin),
            statusClass: `plugins-section__status--${plugin.status}`,
            hasSecretSlots: plugin.secret_slots.length > 0,
        }))
    );
    protected readonly isInitialLoading = computed(() => this.pluginsStore.loading() && !this.pluginsStore.loaded());
    protected readonly isEmpty = computed(() => this.pluginsStore.loaded() && this.rows().length === 0);

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    private readonly pluginsStore = inject(PluginsStoreService);
    private readonly dialog = inject(Dialog);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.reload();
    }

    reload(): void {
        this.loadFailed.set(false);
        this.pluginsStore
            .refresh()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => this.loadFailed.set(true) });
    }

    isBusy(id: number): boolean {
        return this.busyIds().has(id);
    }

    onAddPlugin(): void {
        this.dialog.open<PluginDetail | undefined>(PluginInstallDialogComponent, {
            width: '640px',
            maxWidth: 'calc(100vw - 2rem)',
        });
    }

    onSuspend(plugin: PluginSummary): void {
        this.confirmationDialogService
            .confirm({
                title: 'Suspend plugin',
                message: `Suspend <strong>${escapeHtml(plugin.name)}</strong>? Its flows stop and can't be started, its page is hidden, and its agents and tools can't be used until you resume it.`,
                confirmText: 'Suspend',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) return;
                this.runAction(plugin.id, this.pluginsStore.suspend(plugin.id), `${plugin.name} suspended`);
            });
    }

    onResume(plugin: PluginSummary): void {
        this.runAction(plugin.id, this.pluginsStore.resume(plugin.id), `${plugin.name} resumed`);
    }

    onRetry(plugin: PluginSummary): void {
        this.runAction(plugin.id, this.pluginsStore.retry(plugin.id), 'Preparing knowledge again');
    }

    onEditSecrets(plugin: PluginSummary): void {
        const data: PluginSecretsDialogData = { plugin };
        this.dialog.open<PluginDetail | undefined>(PluginSecretsDialogComponent, {
            width: '560px',
            maxWidth: 'calc(100vw - 2rem)',
            data,
        });
    }

    onDelete(plugin: PluginSummary): void {
        const data: PluginDeleteDialogData = { pluginId: plugin.id, pluginName: plugin.name };
        this.dialog.open<boolean>(PluginDeleteDialogComponent, {
            width: '560px',
            maxWidth: 'calc(100vw - 2rem)',
            data,
        });
    }

    private runAction(id: number, request: Observable<PluginDetail>, successMessage: string): void {
        this.setBusy(id, true);
        request.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => {
                this.setBusy(id, false);
                this.toastService.success(successMessage);
            },
            error: (error: HttpErrorResponse) => {
                this.setBusy(id, false);
                this.toastService.error(toPluginErrorView(error, 'The plugin could not be updated.').message);
            },
        });
    }

    private setBusy(id: number, busy: boolean): void {
        this.busyIds.update((ids) => {
            const next = new Set(ids);
            if (busy) next.add(id);
            else next.delete(id);
            return next;
        });
    }
}
