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
import { PluginDevelopmentPanelComponent } from '../../components/plugin-development-panel/plugin-development-panel.component';
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
    pluginLifecycleActionLabel,
    pluginStateTone,
    pluginTrustBadgeTone,
    pluginTrustLabel,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

export type PluginDetailTab =
    | 'overview'
    | 'organizations'
    | 'settings'
    | 'limits'
    | 'runtime'
    | 'development'
    | 'activity';

/** The tabs only a plugin whose current package has a backend has. */
const BACKEND_TABS: readonly PluginDetailTab[] = ['settings', 'limits', 'runtime'];

/** The plugin list's address. */
const PLUGINS_LIST_ROUTE = '/workspace/plugins';

/** How often the page asks again while the plugin is being deleted or upgraded. */
export const PLUGIN_DETAIL_POLL_MS = 5000;

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
    upgrade: 'outline-primary',
    cancel_upgrade: 'outline-danger',
    retry_upgrade: 'outline-primary',
    restore_backup: 'outline-danger',
};

/**
 * `/workspace/plugins/:identifier`: one plugin's approved package, the organizations it is granted to (with the data
 * removals of deleted organizations) and its activity; for a plugin with a backend also its settings, limits and
 * runtime; while the deployment runs in plugin development mode, its Development tab.
 *
 * The header's buttons are exactly the plugin's `allowed_actions`: "Uninstall…" and "Delete permanently…" open their
 * previews, "Upgrade to <version>…" the pending package's review, "Restore backup…" the Runtime tab's backups;
 * "Reinstall" and "Cancel upgrade" ask for confirmation; "Retry removal" and "Retry" run at once. The banner says what
 * the plugin is going through (uninstalled, being deleted, being upgraded, a restore). While the plugin is being
 * deleted or upgraded, or organizations are still upgrading, the page asks again every few seconds (not while the
 * browser tab is hidden), and says so when a refresh fails. A plugin on screen the server no longer knows was deleted:
 * the page says so and goes back to the list.
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
        PluginDevelopmentPanelComponent,
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
    /** The current package has a backend, or the open upgrade gives the plugin its first one. */
    protected readonly hasBackend = computed(() => {
        const plugin = this.plugin();
        return plugin?.current_package?.contents.has_backend === true || plugin?.open_upgrade?.adds_backend === true;
    });
    private readonly selectedTab = signal<PluginDetailTab>('overview');
    /** The deployment runs in plugin development mode: the Development tab is offered. */
    protected readonly hasDevelopmentTab = computed(() => this.plugin()?.development_mode === true);
    /** The selected tab, or Overview when the plugin does not offer it (now). */
    protected readonly tab = computed<PluginDetailTab>(() => {
        const tab = this.selectedTab();
        if (BACKEND_TABS.includes(tab) && !this.hasBackend()) return 'overview';
        if (tab === 'development' && !this.hasDevelopmentTab()) return 'overview';
        return tab;
    });
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<PluginErrorView | null>(null);
    /** Why the last refresh of a plugin already shown failed; cleared by the next answer. */
    protected readonly pollError = signal<string | null>(null);
    /**
     * Bumped by each "Restore backup…", which opens the Runtime tab and brings its backups into view, again on every
     * click. Picking a tab resets it.
     */
    protected readonly revealBackups = signal(0);
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
        return plugin ? pluginTrustLabel(plugin.trust) : '';
    });
    protected readonly trustTone = computed(() => {
        const plugin = this.plugin();
        return plugin ? pluginTrustBadgeTone(plugin.trust) : 'neutral';
    });
    protected readonly canGrant = computed(() => this.plugin()?.state === 'running');
    /** The plugin's allowed actions as buttons, in the server's order; an action this page does not know is left out. */
    protected readonly actionButtons = computed<LifecycleActionButton[]>(() => {
        const plugin = this.plugin();
        return (plugin?.allowed_actions ?? []).filter(isKnownLifecycleAction).map((action) => ({
            action,
            label: pluginLifecycleActionLabel(action, plugin?.pending_package ?? null),
            type: LIFECYCLE_ACTION_BUTTON_TYPES[action],
        }));
    });
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
        upgrade: () => this.reviewPending(),
        cancel_upgrade: (plugin) => this.cancelUpgrade(plugin),
        retry_upgrade: (plugin) => this.retryUpgrade(plugin),
        restore_backup: () => this.showBackups(),
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
                                this.onLoadFailure(identifier, error);
                                return of(null);
                            })
                        );
                    // The next poll, at the first tick the browser tab is shown; it waits for the previous answer.
                    const nextPoll = () =>
                        timer(PLUGIN_DETAIL_POLL_MS, PLUGIN_DETAIL_POLL_MS).pipe(
                            filter(() => !this.document.hidden),
                            take(1),
                            switchMap(fetchPlugin)
                        );
                    return fetchPlugin().pipe(
                        tap(() => this.isLoading.set(false)),
                        // After a failed answer the plugin shown decides, so one failure does not stop the polling.
                        expand((plugin) => (needsPolling(plugin ?? this.plugin()) ? nextPoll() : EMPTY))
                    );
                }),
                takeUntilDestroyed()
            )
            .subscribe((plugin) => {
                if (!plugin) return;
                this.loadError.set(null);
                this.pollError.set(null);
                this.plugin.set(plugin);
            });
    }

    protected selectTab(tab: PluginDetailTab): void {
        this.selectedTab.set(tab);
        this.revealBackups.set(0);
    }

    /**
     * Reloads the plugin (its state follows the runtime, its count of active grants the grants) through the same
     * pipeline as the polling, so an older answer never replaces a newer one; a failure keeps what is shown.
     */
    protected refreshPlugin(): void {
        this.reload();
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
                    // Restarts the polling, which follows an upgrade the approval started.
                    this.reload();
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

    private cancelUpgrade(plugin: PluginDetail): void {
        this.confirmation
            .confirm({
                title: 'Cancel the upgrade?',
                message: escapeHtml(cancelUpgradeText(plugin)),
                type: 'warning',
                confirmText: 'Cancel upgrade',
                cancelText: 'Keep it',
            })
            .pipe(
                filter((answer) => answer === true),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() =>
                this.send(
                    this.storage.cancelUpgrade(plugin.identifier),
                    `The upgrade of ${plugin.name} is cancelled.`,
                    "Couldn't cancel the upgrade."
                )
            );
    }

    private retryUpgrade(plugin: PluginDetail): void {
        this.send(
            this.storage.retryUpgrade(plugin.identifier),
            `The plugin node tries the upgrade of ${plugin.name} again.`,
            "Couldn't retry the upgrade."
        );
    }

    /** The backups live in the Runtime tab; it brings them into view. */
    private showBackups(): void {
        this.selectedTab.set('runtime');
        this.revealBackups.update((count) => count + 1);
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
     * A plugin already shown that the server no longer knows was deleted: say so and go back to the list. A plugin it
     * never knew is not found. Another failure keeps a plugin already shown, and says the refresh failed; a first load
     * says why.
     */
    private onLoadFailure(identifier: string, error: unknown): void {
        const shown = this.plugin()?.identifier === identifier ? this.plugin() : null;
        if (isNotFound(error) && shown) {
            this.leaveDeleted(shown);
            return;
        }
        if (shown) {
            this.pollError.set(toPluginErrorView(error, "Couldn't load the plugin.").message);
            return;
        }
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

/** "Cancel the upgrade of Weather to 0.7.0? 0.7.0 is deleted, and Weather goes on with 0.6.0." */
function cancelUpgradeText(plugin: PluginDetail): string {
    const upgrade = plugin.open_upgrade;
    if (!upgrade) return `Cancel the upgrade of ${plugin.name}?`;
    const offline =
        plugin.state === 'maintenance'
            ? ` It starts ${upgrade.from_version} again and is back in a minute or two.`
            : '';
    return (
        `Cancel the upgrade of ${plugin.name} to ${upgrade.to_version}? ${upgrade.to_version} is deleted, and ` +
        `${plugin.name} goes on with ${upgrade.from_version}.${offline}`
    );
}

/** The server finishes these on its own: a deletion, an open upgrade (and its restore), organizations upgrading. */
function needsPolling(plugin: PluginDetail | null): boolean {
    if (!plugin) return false;
    return plugin.state === 'purging' || plugin.open_upgrade !== null || plugin.upgrade_hooks.upgrading > 0;
}

function isNotFound(error: unknown): boolean {
    return error instanceof HttpErrorResponse && error.status === HttpStatusCode.NotFound;
}

function isKnownLifecycleAction(action: string): action is PluginLifecycleAction {
    return Object.hasOwn(PLUGIN_LIFECYCLE_ACTION_LABELS, action);
}
