import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
    TabButtonComponent,
} from '@shared/components';
import { catchError, finalize, of, switchMap, tap } from 'rxjs';

import { PluginBadgeComponent } from '../../components/plugin-badge/plugin-badge.component';
import { PluginGrantsTableComponent } from '../../components/plugin-grants-table/plugin-grants-table.component';
import { PluginIconComponent } from '../../components/plugin-icon/plugin-icon.component';
import { PluginReviewPanelComponent } from '../../components/plugin-review-panel/plugin-review-panel.component';
import { PluginDetail } from '../../models/plugin-admin.model';
import { PluginErrorView } from '../../models/plugin-error.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    PLUGIN_STATE_LABELS,
    PLUGIN_TRUST_LABELS,
    pluginStateTone,
    pluginTrustTone,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

export type PluginDetailTab = 'overview' | 'organizations';

/** The plugin list's address. */
const PLUGINS_LIST_ROUTE = '/workspace/plugins';

/** `/workspace/plugins/:identifier`: one plugin's approved package and the organizations it is granted to. */
@Component({
    selector: 'app-plugin-admin-detail-page',
    imports: [
        AppSvgIconComponent,
        ButtonComponent,
        FetchErrorStateComponent,
        LoadingSpinnerComponent,
        PluginBadgeComponent,
        PluginGrantsTableComponent,
        PluginIconComponent,
        PluginReviewPanelComponent,
        RouterLink,
        TabButtonComponent,
    ],
    templateUrl: './plugin-admin-detail-page.component.html',
    styleUrl: './plugin-admin-detail-page.component.scss',
})
export class PluginAdminDetailPageComponent {
    /** The route param. */
    readonly identifier = input.required<string>();

    protected readonly tab = signal<PluginDetailTab>('overview');
    protected readonly plugin = signal<PluginDetail | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<PluginErrorView | null>(null);
    protected readonly stateLabel = computed(() => {
        const plugin = this.plugin();
        return plugin ? PLUGIN_STATE_LABELS[plugin.state] : '';
    });
    protected readonly stateTone = computed(() => {
        const plugin = this.plugin();
        return plugin ? pluginStateTone(plugin.state) : 'neutral';
    });
    protected readonly trustLabel = computed(() => {
        const plugin = this.plugin();
        return plugin ? PLUGIN_TRUST_LABELS[plugin.trust] : '';
    });
    protected readonly trustTone = computed(() => {
        const plugin = this.plugin();
        return plugin ? pluginTrustTone(plugin.trust) : 'neutral';
    });
    protected readonly canGrant = computed(() => this.plugin()?.state === 'running');
    protected readonly errorTitle = computed(() =>
        this.loadError()?.code === 'plugin_not_found' ? 'Plugin not found' : "Couldn't load the plugin"
    );
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({ identifier: this.identifier(), reload: this.reloads() }));

    protected readonly listRoute = PLUGINS_LIST_ROUTE;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly dialogs = inject(PluginDialogsService);
    private readonly router = inject(Router);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => {
                    this.isLoading.set(true);
                    this.loadError.set(null);
                }),
                switchMap(({ identifier }) =>
                    this.storage.getPlugin(identifier).pipe(
                        catchError((error: unknown) => {
                            this.plugin.set(null);
                            this.loadError.set(toPluginErrorView(error, "Couldn't load the plugin."));
                            return of(null);
                        }),
                        finalize(() => this.isLoading.set(false))
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((plugin) => {
                if (plugin) this.plugin.set(plugin);
            });
    }

    protected selectTab(tab: PluginDetailTab): void {
        this.tab.set(tab);
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    protected reviewPending(): void {
        const pending = this.plugin()?.pending_package;
        if (!pending) return;
        this.dialogs
            .openReview({ packageId: pending.id })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result?.kind === 'approved') {
                    this.plugin.set(result.plugin);
                } else if (result?.kind === 'rejected') {
                    this.reloadOrLeave();
                }
            });
    }

    /** After a rejection the plugin is gone when it had nothing approved; then the list is the place to be. */
    private reloadOrLeave(): void {
        this.storage
            .getPlugin(this.identifier())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (plugin) => this.plugin.set(plugin),
                error: (error: unknown) => {
                    if (error instanceof HttpErrorResponse && error.status === HttpStatusCode.NotFound) {
                        void this.router.navigateByUrl(PLUGINS_LIST_ROUTE);
                        return;
                    }
                    this.loadError.set(toPluginErrorView(error, "Couldn't load the plugin."));
                },
            });
    }
}
