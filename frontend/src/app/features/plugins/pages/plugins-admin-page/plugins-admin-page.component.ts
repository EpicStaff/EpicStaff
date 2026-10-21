import { Component, computed, DestroyRef, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    LoadingSpinnerComponent,
    TableRow,
} from '@shared/components';
import { filter, switchMap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginBadgeComponent } from '../../components/plugin-badge/plugin-badge.component';
import { PluginIconComponent } from '../../components/plugin-icon/plugin-icon.component';
import { PackageReview, PluginPendingPackage, PluginSummary } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    PLUGIN_STATE_LABELS,
    PLUGIN_TRUST_LABELS,
    PluginBadgeTone,
    pluginStateTone,
    pluginTrustTone,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

const COLUMNS: AppTableColumnDef[] = [
    { key: 'icon', label: '', width: '48px' },
    { key: 'name', label: 'Name', width: 'minmax(160px, 2fr)' },
    { key: 'identifier', label: 'Identifier', width: 'minmax(120px, 1.5fr)' },
    { key: 'version', label: 'Version', width: 'minmax(80px, 1fr)' },
    { key: 'state', label: 'State', width: 'minmax(180px, 1.5fr)' },
    { key: 'trust', label: 'Trust', width: 'minmax(100px, 1fr)' },
    { key: 'grants', label: 'Active grants', width: 'minmax(110px, 1fr)' },
    { key: 'pending', label: 'Pending', width: 'minmax(150px, 1.5fr)' },
];

/** `/workspace/plugins`: every plugin on the platform, and the upload that starts a new one. SuperAdmin only. */
@Component({
    selector: 'app-plugins-admin-page',
    imports: [
        AppTableCellDirective,
        AppTableComponent,
        ButtonComponent,
        LoadingSpinnerComponent,
        PluginBadgeComponent,
        PluginIconComponent,
    ],
    templateUrl: './plugins-admin-page.component.html',
    styleUrl: './plugins-admin-page.component.scss',
})
export class PluginsAdminPageComponent implements OnInit {
    protected readonly plugins = inject(PluginsAdminStorageService).plugins;
    protected readonly isLoading = inject(PluginsAdminStorageService).isLoading;
    protected readonly countLabel = computed(() => {
        const count = this.plugins().length;
        return `${count} ${count === 1 ? 'plugin' : 'plugins'}`;
    });
    protected readonly rows = computed<TableRow[]>(() =>
        this.plugins().map((plugin) => ({ id: plugin.identifier, name: plugin.name }))
    );
    private readonly pluginsByIdentifier = computed(
        () => new Map(this.plugins().map((plugin) => [plugin.identifier, plugin]))
    );

    protected readonly columns = COLUMNS;

    private readonly adminStorage = inject(PluginsAdminStorageService);
    private readonly dialogs = inject(PluginDialogsService);
    private readonly router = inject(Router);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.adminStorage
            .loadPlugins()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: (error: unknown) =>
                    this.toast.error(toPluginErrorView(error, "Couldn't load the plugins.").message),
            });
    }

    protected pluginOf(row: TableRow): PluginSummary | undefined {
        return this.pluginsByIdentifier().get(row['id'] as string);
    }

    protected stateLabel(plugin: PluginSummary): string {
        return PLUGIN_STATE_LABELS[plugin.state];
    }

    protected stateTone(plugin: PluginSummary): PluginBadgeTone {
        return pluginStateTone(plugin.state);
    }

    protected trustLabel(plugin: PluginSummary): string {
        return PLUGIN_TRUST_LABELS[plugin.trust];
    }

    protected trustTone(plugin: PluginSummary): PluginBadgeTone {
        return pluginTrustTone(plugin.trust);
    }

    protected reviewLabel(plugin: PluginSummary, pending: PluginPendingPackage): string {
        return `Review ${plugin.name} ${pending.version}`;
    }

    protected openPlugin(row: TableRow): void {
        void this.router.navigate(['/workspace/plugins', row['id'] as string]);
    }

    protected upload(): void {
        this.dialogs
            .openUpload()
            .pipe(
                filter((review): review is PackageReview => review !== undefined),
                switchMap((review) => this.dialogs.openReview({ review })),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    protected reviewPending(plugin: PluginSummary, event: Event): void {
        event.stopPropagation();
        if (!plugin.pending_package) return;
        this.dialogs
            .openReview({ packageId: plugin.pending_package.id })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe();
    }
}
