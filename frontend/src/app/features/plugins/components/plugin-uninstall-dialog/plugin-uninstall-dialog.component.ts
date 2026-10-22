import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent, LoadingSpinnerComponent } from '@shared/components';
import { filter, finalize } from 'rxjs';

import { PluginDetail } from '../../models/plugin-admin.model';
import { PluginPreviewListView } from '../../models/plugin-preview-view.model';
import { PluginPurgePreview } from '../../models/plugin-purge-preview.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import {
    ownedResourcesListView,
    previewOrganizationItem,
    toPreviewListView,
} from '../../utils/plugin-preview-view.util';
import { PluginPreviewSectionComponent } from '../plugin-preview-section/plugin-preview-section.component';

export interface PluginUninstallDialogData {
    identifier: string;
    pluginName: string;
}

/** The dialog's title element; pass it as `ariaLabelledBy` when opening the dialog. */
export const PLUGIN_UNINSTALL_DIALOG_TITLE_ID = 'plugin-uninstall-dialog-title';

/** The preview as the dialog's sections show it. */
interface UninstallPreviewView {
    organizations: PluginPreviewListView;
    owned: PluginPreviewListView;
    dataKeptUntil: string;
}

/**
 * Uninstalls a plugin after showing what that stops: the organizations it is granted to, with their state and what it
 * owns in each, and what it owns in all of them. Its data is kept until the grace period ends, and Reinstall brings it
 * all back, so no typed phrase is asked for; but uninstalling stops the plugin everywhere, so it waits for the
 * preview. Closes with the plugin uninstalled. A click outside does not close it; Escape, Cancel and the close button
 * do, except while the uninstall is under way.
 */
@Component({
    selector: 'app-plugin-uninstall-dialog',
    imports: [AppSvgIconComponent, ButtonComponent, DatePipe, LoadingSpinnerComponent, PluginPreviewSectionComponent],
    templateUrl: './plugin-uninstall-dialog.component.html',
    styleUrl: './plugin-uninstall-dialog.component.scss',
})
export class PluginUninstallDialogComponent implements OnInit {
    protected readonly preview = signal<PluginPurgePreview | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly isUninstalling = signal(false);
    protected readonly uninstallError = signal<string | null>(null);
    protected readonly view = computed(() => {
        const preview = this.preview();
        return preview ? toPreviewView(preview) : null;
    });
    protected readonly canUninstall = computed(
        () => this.preview() !== null && !this.isLoading() && !this.isUninstalling()
    );

    protected readonly data = inject<PluginUninstallDialogData>(DIALOG_DATA);
    protected readonly ownedHeading = `What ${this.data.pluginName} owns in all organizations`;
    protected readonly organizationsEmptyText = `None. ${this.data.pluginName} is not granted to any organization.`;
    protected readonly titleId = PLUGIN_UNINSTALL_DIALOG_TITLE_ID;

    private readonly dialogRef = inject<DialogRef<PluginDetail>>(DialogRef);
    private readonly storage = inject(PluginsAdminStorageService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.dialogRef.keydownEvents
            .pipe(
                filter((event) => event.key === 'Escape'),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.close());
        this.loadPreview();
    }

    protected loadPreview(): void {
        this.isLoading.set(true);
        this.loadError.set(null);
        this.storage
            .getPluginPurgePreview(this.data.identifier)
            .pipe(
                finalize(() => this.isLoading.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (preview) => this.preview.set(preview),
                error: (error: unknown) => {
                    this.preview.set(null);
                    this.loadError.set(toPluginErrorView(error, "Couldn't load what uninstalling would stop.").message);
                },
            });
    }

    protected uninstall(): void {
        if (!this.canUninstall()) return;
        this.isUninstalling.set(true);
        this.uninstallError.set(null);
        this.storage
            .uninstallPlugin(this.data.identifier)
            .pipe(
                finalize(() => this.isUninstalling.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (plugin) => this.dialogRef.close(plugin),
                error: (error: unknown) =>
                    this.uninstallError.set(toPluginErrorView(error, "Couldn't uninstall the plugin.").message),
            });
    }

    protected close(): void {
        if (this.isUninstalling()) return;
        this.dialogRef.close();
    }
}

function toPreviewView(preview: PluginPurgePreview): UninstallPreviewView {
    return {
        organizations: toPreviewListView(preview.organizations, previewOrganizationItem),
        owned: ownedResourcesListView(preview.owned_resources),
        dataKeptUntil: preview.data_kept_until,
    };
}
