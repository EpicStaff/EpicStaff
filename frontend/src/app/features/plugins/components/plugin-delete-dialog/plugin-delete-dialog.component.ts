import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { hasModifierKey } from '@angular/cdk/keycodes';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
    Spinner2Component,
} from '@shared/components';
import { filter, merge, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { buildDeleteBreakdownItems } from '../../../role-base-access/utils';
import { PluginDeletePreview } from '../../models/plugin.model';
import { PluginsApiService } from '../../services/plugins-api.service';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { describeMissingPermission, resourceTypeLabel } from '../../utils/plugin-display.util';
import { PluginErrorView, toPluginErrorView } from '../../utils/plugin-error.util';

export interface PluginDeleteDialogData {
    pluginId: number;
    pluginName: string;
}

interface ResourceGroup {
    type: string;
    label: string;
    names: string[];
}

@Component({
    selector: 'app-plugin-delete-dialog',
    imports: [
        AppSvgIconComponent,
        ButtonComponent,
        FetchErrorStateComponent,
        LoadingSpinnerComponent,
        Spinner2Component,
        MatTooltip,
    ],
    templateUrl: './plugin-delete-dialog.component.html',
    styleUrls: ['./plugin-delete-dialog.component.scss'],
})
export class PluginDeleteDialogComponent implements OnInit {
    protected readonly preview = signal<PluginDeletePreview | null>(null);
    protected readonly previewFailed = signal(false);
    protected readonly deleting = signal(false);
    protected readonly deleteError = signal<PluginErrorView | null>(null);

    protected readonly pluginLabel = computed(() => {
        const plugin = this.preview()?.plugin;
        return plugin ? `${plugin.name} v${plugin.version}` : this.data.pluginName;
    });
    protected readonly breakdown = computed(() => {
        const affected = this.preview()?.affected_resources ?? {};
        const nonZero = Object.fromEntries(Object.entries(affected).filter(([, count]) => count > 0));
        return buildDeleteBreakdownItems(nonZero);
    });
    protected readonly resourceGroups = computed<ResourceGroup[]>(() => {
        const groups = new Map<string, string[]>();
        for (const resource of this.preview()?.resources ?? []) {
            if (!resource.exists || !resource.name) continue;
            groups.set(resource.type, [...(groups.get(resource.type) ?? []), resource.name]);
        }
        return [...groups.entries()].map(([type, names]) => ({
            type,
            label: resourceTypeLabel(type, names.length),
            names,
        }));
    });
    /** One line per delete permission the role lacks; delete would answer 403 while any is listed. */
    protected readonly blockers = computed(() =>
        (this.preview()?.missing_permissions ?? []).map(
            (permission) => `Your role can't ${describeMissingPermission(permission)}.`
        )
    );
    protected readonly canDelete = computed(() => !!this.preview() && this.blockers().length === 0 && !this.deleting());
    protected readonly alreadyDeletedCount = computed(
        () => (this.preview()?.resources ?? []).filter((resource) => !resource.exists).length
    );
    protected readonly externalUsageLines = computed(() =>
        (this.preview()?.external_usages ?? []).flatMap((usage) =>
            usage.used_by.map(
                (user) =>
                    `${resourceTypeLabel(user.type, 1)} '${user.name}' uses ${resourceTypeLabel(usage.type, 1).toLowerCase()} '${usage.name}'`
            )
        )
    );

    protected readonly data: PluginDeleteDialogData = inject(DIALOG_DATA);

    private readonly dialogRef = inject(DialogRef<boolean>);
    private readonly pluginsApiService = inject(PluginsApiService);
    private readonly pluginsStore = inject(PluginsStoreService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.routeDismissThroughClose();
        this.loadPreview();
    }

    loadPreview(): void {
        this.previewFailed.set(false);
        this.preview.set(null);
        this.pluginsApiService
            .getDeletePreview(this.data.pluginId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (preview) => this.preview.set(preview),
                error: () => this.previewFailed.set(true),
            });
    }

    confirmDelete(): void {
        if (!this.canDelete()) return;
        this.deleting.set(true);
        this.deleteError.set(null);
        this.pluginsStore
            .delete(this.data.pluginId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.deleting.set(false);
                    this.toastService.success(`${this.data.pluginName} deleted`);
                    this.dialogRef.close(true);
                },
                error: (error: HttpErrorResponse) => {
                    this.deleting.set(false);
                    this.deleteError.set(toPluginErrorView(error, 'The plugin could not be deleted.'));
                },
            });
    }

    close(): void {
        if (this.deleting()) return;
        this.dialogRef.close(false);
    }

    /** Backdrop click and Escape go through close(), so they are ignored while deleting. */
    private routeDismissThroughClose(): void {
        this.dialogRef.disableClose = true;
        merge(
            this.dialogRef.backdropClick,
            this.dialogRef.keydownEvents.pipe(
                filter((event) => event.key === 'Escape' && !hasModifierKey(event)),
                tap((event) => event.preventDefault())
            )
        )
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.close());
    }
}
