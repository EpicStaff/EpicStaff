import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, ConfirmationDialogService } from '@shared/components';
import { escapeHtml } from '@shared/utils';
import { filter, finalize, Observable } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginOrgRemovedJob, PluginOrgRemovedJobAction } from '../../models/plugin-admin.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { PLUGIN_DATA_REMOVAL_ACTION_LABELS } from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

/** A button of a data removal. */
interface DataRemovalButton {
    action: PluginOrgRemovedJobAction;
    label: string;
    type: 'outline-primary' | 'outline-secondary';
}

const DATA_REMOVAL_BUTTON_TYPES: Readonly<Record<PluginOrgRemovedJobAction, DataRemovalButton['type']>> = {
    retry: 'outline-primary',
    skip: 'outline-secondary',
};

/**
 * The Retry and Skip buttons of one data removal (a run of the plugin's organization removed hook), exactly as the
 * job's `allowed_actions` lists them. Retry runs at once; Skip asks first, because the plugin then keeps that
 * organization's data until the plugin is deleted. Tells its container once a request is answered, whatever the
 * answer, so the container shows the job as it is now.
 */
@Component({
    selector: 'app-plugin-data-removal-actions',
    imports: [ButtonComponent],
    templateUrl: './plugin-data-removal-actions.component.html',
    styleUrl: './plugin-data-removal-actions.component.scss',
})
export class PluginDataRemovalActionsComponent {
    readonly identifier = input.required<string>();
    readonly pluginName = input.required<string>();
    readonly job = input.required<PluginOrgRemovedJob>();
    /** A request about the job was answered; the job may have changed or gone. */
    readonly changed = output<void>();

    protected readonly isBusy = signal(false);
    protected readonly buttons = computed<DataRemovalButton[]>(() =>
        this.job()
            .allowed_actions.filter(isKnownAction)
            .map((action) => ({
                action,
                label: PLUGIN_DATA_REMOVAL_ACTION_LABELS[action],
                type: DATA_REMOVAL_BUTTON_TYPES[action],
            }))
    );

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    /** One handler per action, so a new action does not build until it has one. */
    private readonly actionHandlers: Readonly<Record<PluginOrgRemovedJobAction, (job: PluginOrgRemovedJob) => void>> = {
        retry: (job) => this.retry(job),
        skip: (job) => this.skip(job),
    };

    protected runAction(action: PluginOrgRemovedJobAction): void {
        if (this.isBusy()) return;
        this.actionHandlers[action](this.job());
    }

    private retry(job: PluginOrgRemovedJob): void {
        const pluginName = this.pluginName();
        this.send(
            this.storage.retryOrgRemovedJob(this.identifier(), job.id),
            `${pluginName} tries again to delete its data for ${job.organization.name}.`,
            "Couldn't retry the data removal."
        );
    }

    private skip(job: PluginOrgRemovedJob): void {
        const pluginName = escapeHtml(this.pluginName());
        const organizationName = escapeHtml(job.organization.name);
        this.confirmation
            .confirm({
                title: 'Skip the data removal?',
                message:
                    `Skip? ${pluginName}'s data for ${organizationName} then stays where ${pluginName} keeps it ` +
                    `until ${pluginName} is deleted.`,
                type: 'warning',
                confirmText: 'Skip',
                cancelText: 'Cancel',
            })
            .pipe(
                filter((answer) => answer === true),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() =>
                this.send(
                    this.storage.skipOrgRemovedJob(this.identifier(), job.id),
                    `Skipped. ${this.pluginName()}'s data for ${job.organization.name} stays until ${this.pluginName()} is deleted.`,
                    "Couldn't skip the data removal."
                )
            );
    }

    /** Sends the request with the buttons waiting; says how it went, then lets the container reload. */
    private send(request: Observable<PluginOrgRemovedJob>, successMessage: string, failureFallback: string): void {
        this.isBusy.set(true);
        request
            .pipe(
                finalize(() => this.isBusy.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success(successMessage);
                    this.changed.emit();
                },
                error: (error: unknown) => {
                    this.toast.error(toPluginErrorView(error, failureFallback).message);
                    this.changed.emit();
                },
            });
    }
}

function isKnownAction(action: string): action is PluginOrgRemovedJobAction {
    return Object.hasOwn(PLUGIN_DATA_REMOVAL_ACTION_LABELS, action);
}
