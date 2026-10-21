import { DOCUMENT } from '@angular/common';
import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
    TabButtonComponent,
} from '@shared/components';
import { escapeHtml } from '@shared/utils';
import { catchError, EMPTY, expand, filter, finalize, Observable, of, switchMap, take, tap, timer } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginAdminActivityComponent } from '../../components/plugin-admin-activity/plugin-admin-activity.component';
import { PluginBadgeComponent } from '../../components/plugin-badge/plugin-badge.component';
import { PluginDataRemovalsComponent } from '../../components/plugin-data-removals/plugin-data-removals.component';
import { PluginGrantsTableComponent } from '../../components/plugin-grants-table/plugin-grants-table.component';
import { PluginIconComponent } from '../../components/plugin-icon/plugin-icon.component';
import { PluginLifecycleBannerComponent } from '../../components/plugin-lifecycle-banner/plugin-lifecycle-banner.component';
import { PluginLimitsFormComponent } from '../../components/plugin-limits-form/plugin-limits-form.component';
import { PluginReviewPanelComponent } from '../../components/plugin-review-panel/plugin-review-panel.component';
import { PluginRuntimePanelComponent } from '../../components/plugin-runtime-panel/plugin-runtime-panel.component';
import { PluginSettingsFormComponent } from '../../components/plugin-settings-form/plugin-settings-form.component';
import { PluginDetail, PluginLifecycleAction } from '../../models/plugin-admin.model';
import { PluginErrorView } from '../../models/plugin-error.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    PLUGIN_LIFECYCLE_ACTION_LABELS,
    PLUGIN_STATE_LABELS,
    PLUGIN_TRUST_LABELS,
    pluginStateTone,
    pluginTrustTone,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

export type PluginDetailTab = 'overview' | 'organizations' | 'settings' | 'limits' | 'runtime' | 'activity';

/** The tabs only a plugin whose current package has a backend has. */
const BACKEND_TABS: readonly PluginDetailTab[] = ['settings', 'limits', 'runtime'];

/** The plugin list's address. */
const PLUGINS_LIST_ROUTE = '/workspace/plugins';

/** How often the page asks again while the plugin is being deleted. */
export const PLUGIN_DELETION_POLL_MS = 5000;

/** A header button. */
interface LifecycleActionButton {
    action: PluginLifecycleAction;
    label: string;
    type: 'outline-primary' | 'outline-danger';
}

const LIFECYCLE_ACTION_BUTTON_TYPES: Readonly<Record<PluginLifecycleAction, LifecycleActionButton['type']>> = {
    uninstall: 'outline-danger',
    reinstall: 'outline-primary',
    purge: 'outline-danger',
    retry_removal: 'outline-primary',
};

/**
 * `/workspace/plugins/:identifier`: one plugin's approved package, the organizations it is granted to (with the data
 * removals of deleted organizations) and its activity; for a plugin with a backend also its settings, limits and
 * runtime.
 *
 * The header's buttons are exactly the plugin's `allowed_actions`: "Uninstall…" and "Delete permanently…" open their
 * previews, "Reinstall" asks for confirmation, "Retry removal" runs at once. An uninstalled plugin says until when its
 * data is kept; a plugin being deleted shows how far that has come, and the page asks again every few seconds (not
 * while the browser tab is hidden) until the server no longer knows the plugin: then it says so and goes back to the
 * list.
 */
@Component({
    selector: 'app-plugin-admin-detail-page',
    imports: [
        AppSvgIconComponent,
        ButtonComponent,
        FetchErrorStateComponent,
        LoadingSpinnerComponent,
        PluginAdminActivityComponent,
        PluginBadgeComponent,
        PluginDataRemovalsComponent,
        PluginGrantsTableComponent,
        PluginIconComponent,
        PluginLifecycleBannerComponent,
        PluginLimitsFormComponent,
        PluginReviewPanelComponent,
        PluginRuntimePanelComponent,
        PluginSettingsFormComponent,
        RouterLink,
        TabButtonComponent,
    ],
    templateUrl: './plugin-admin-detail-page.component.html',
    styleUrl: './plugin-admin-detail-page.component.scss',
})
export class PluginAdminDetailPageComponent {
    /** The route param. */
    readonly identifier = input.required<string>();

    protected readonly plugin = signal<PluginDetail | null>(null);
    protected readonly hasBackend = computed(() => this.plugin()?.current_package?.contents.has_backend === true);
    private readonly selectedTab = signal<PluginDetailTab>('overview');
    /** The selected tab, or Overview when it is a backend tab and the plugin has no backend. */
    protected readonly tab = computed<PluginDetailTab>(() => {
        const tab = this.selectedTab();
        return BACKEND_TABS.includes(tab) && !this.hasBackend() ? 'overview' : tab;
    });
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<PluginErrorView | null>(null);
    /** A header action is under way; the header's buttons wait. */
    protected readonly isActing = signal(false);
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
    /** The plugin's allowed actions as buttons, in the server's order; an action this page does not know is left out. */
    protected readonly actionButtons = computed<LifecycleActionButton[]>(() =>
        (this.plugin()?.allowed_actions ?? []).filter(isKnownLifecycleAction).map((action) => ({
            action,
            label: PLUGIN_LIFECYCLE_ACTION_LABELS[action],
            type: LIFECYCLE_ACTION_BUTTON_TYPES[action],
        }))
    );
    protected readonly errorTitle = computed(() =>
        this.loadError()?.code === 'plugin_not_found' ? 'Plugin not found' : "Couldn't load the plugin"
    );
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({ identifier: this.identifier(), reload: this.reloads() }));

    protected readonly listRoute = PLUGINS_LIST_ROUTE;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly dialogs = inject(PluginDialogsService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);
    private readonly router = inject(Router);
    private readonly document = inject(DOCUMENT);
    private readonly destroyRef = inject(DestroyRef);
    /** One handler per action, so a new action does not build until it has one. */
    private readonly actionHandlers: Readonly<Record<PluginLifecycleAction, (plugin: PluginDetail) => void>> = {
        uninstall: (plugin) => this.openUninstall(plugin),
        reinstall: (plugin) => this.reinstall(plugin),
        purge: (plugin) => this.openPurge(plugin),
        retry_removal: (plugin) => this.retryRemoval(plugin),
    };

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => {
                    this.isLoading.set(true);
                    this.loadError.set(null);
                }),
                switchMap(({ identifier }) => {
                    const fetchPlugin = () =>
                        this.storage.getPlugin(identifier).pipe(
                            catchError((error: unknown) => {
                                this.onLoadFailure(error);
                                return of(null);
                            })
                        );
                    // The next poll, at the first tick the browser tab is shown; it waits for the previous answer.
                    const nextPoll = () =>
                        timer(PLUGIN_DELETION_POLL_MS, PLUGIN_DELETION_POLL_MS).pipe(
                            filter(() => !this.document.hidden),
                            take(1),
                            switchMap(fetchPlugin)
                        );
                    return fetchPlugin().pipe(
                        tap(() => this.isLoading.set(false)),
                        // After a failed answer the plugin shown decides, so one failure does not stop the polling.
                        expand((plugin) => (isDeleting(plugin ?? this.plugin()) ? nextPoll() : EMPTY))
                    );
                }),
                takeUntilDestroyed()
            )
            .subscribe((plugin) => {
                if (!plugin) return;
                this.loadError.set(null);
                this.plugin.set(plugin);
            });
    }

    protected selectTab(tab: PluginDetailTab): void {
        this.selectedTab.set(tab);
    }

    /**
     * Reloads the plugin quietly (its state follows the runtime, its count of active grants the grants); a failure
     * keeps what is shown.
     */
    protected refreshPlugin(): void {
        this.storage
            .getPlugin(this.identifier())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (plugin) => this.plugin.set(plugin),
                error: () => undefined,
            });
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    protected runAction(action: PluginLifecycleAction): void {
        const plugin = this.plugin();
        if (!plugin || this.isActing()) return;
        this.actionHandlers[action](plugin);
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

    private openUninstall(plugin: PluginDetail): void {
        this.dialogs
            .openUninstall({ identifier: plugin.identifier, pluginName: plugin.name })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((uninstalled) => {
                if (uninstalled) {
                    this.plugin.set(uninstalled);
                    this.toast.success(`${plugin.name} is uninstalled.`);
                }
                // Also after Cancel: the dialog may have been refused because the plugin moved meanwhile.
                this.reload();
            });
    }

    private reinstall(plugin: PluginDetail): void {
        this.confirmation
            .confirm({
                title: 'Reinstall the plugin?',
                message: `Reinstall ${escapeHtml(plugin.name)}? Organizations it was uninstalled from get it back, with their data.`,
                type: 'warning',
                confirmText: 'Reinstall',
                cancelText: 'Cancel',
            })
            .pipe(
                filter((answer) => answer === true),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() =>
                this.send(
                    this.storage.reinstallPlugin(plugin.identifier),
                    `${plugin.name} is reinstalled.`,
                    "Couldn't reinstall the plugin."
                )
            );
    }

    private openPurge(plugin: PluginDetail): void {
        this.dialogs
            .openPluginPurge({ identifier: plugin.identifier, pluginName: plugin.name })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((deleting) => {
                if (deleting) {
                    this.plugin.set(deleting);
                    this.toast.success(`Deleting ${plugin.name}.`);
                }
                // Restarts loading, and with it the polling of a plugin being deleted.
                this.reload();
            });
    }

    private retryRemoval(plugin: PluginDetail): void {
        this.send(
            this.storage.retryRemoval(plugin.identifier),
            `The plugin node tries again to remove ${plugin.name}.`,
            "Couldn't retry the removal."
        );
    }

    /** Sends a header action with the buttons waiting; then shows the plugin as it is now, and restarts polling. */
    private send(request: Observable<PluginDetail>, successMessage: string, failureFallback: string): void {
        this.isActing.set(true);
        request
            .pipe(
                finalize(() => this.isActing.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (plugin) => {
                    this.plugin.set(plugin);
                    this.toast.success(successMessage);
                    this.reload();
                },
                error: (error: unknown) => {
                    this.toast.error(toPluginErrorView(error, failureFallback).message);
                    // The plugin may have moved meanwhile: show what it is now.
                    this.reload();
                },
            });
    }

    /**
     * A plugin being deleted that the server no longer knows is deleted: say so and go back to the list. Any other
     * plugin it no longer knows is not found. Another failure keeps a plugin already shown; a first load says why.
     */
    private onLoadFailure(error: unknown): void {
        const shown = this.plugin();
        if (isNotFound(error) && shown?.state === 'purging') {
            this.leaveDeleted(shown);
            return;
        }
        if (shown && !isNotFound(error)) return;
        this.plugin.set(null);
        this.loadError.set(toPluginErrorView(error, "Couldn't load the plugin."));
    }

    private leaveDeleted(plugin: PluginDetail): void {
        this.plugin.set(null);
        this.storage.forgetPlugin(plugin.identifier);
        this.toast.success(`${plugin.name} was deleted.`);
        void this.router.navigateByUrl(PLUGINS_LIST_ROUTE);
    }

    /** After a rejection the plugin is gone when it had nothing approved; then the list is the place to be. */
    private reloadOrLeave(): void {
        this.storage
            .getPlugin(this.identifier())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (plugin) => this.plugin.set(plugin),
                error: (error: unknown) => {
                    if (isNotFound(error)) {
                        void this.router.navigateByUrl(PLUGINS_LIST_ROUTE);
                        return;
                    }
                    this.loadError.set(toPluginErrorView(error, "Couldn't load the plugin."));
                },
            });
    }
}

function isDeleting(plugin: PluginDetail | null): boolean {
    return plugin?.state === 'purging';
}

function isNotFound(error: unknown): boolean {
    return error instanceof HttpErrorResponse && error.status === HttpStatusCode.NotFound;
}

function isKnownLifecycleAction(action: string): action is PluginLifecycleAction {
    return Object.hasOwn(PLUGIN_LIFECYCLE_ACTION_LABELS, action);
}
