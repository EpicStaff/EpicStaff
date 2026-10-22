import { DatePipe, DecimalPipe, DOCUMENT } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { ButtonComponent, ConfirmationDialogService, LoadingSpinnerComponent } from '@shared/components';
import { escapeHtml, formatFileSize } from '@shared/utils';
import { catchError, EMPTY, exhaustMap, filter, finalize, switchMap, timer } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginUpgrade } from '../../models/plugin-admin.model';
import { PluginBlockedReason, PluginRuntimeResponse } from '../../models/plugin-backend.model';
import { PluginErrorView } from '../../models/plugin-error.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    PLUGIN_DATABASE_STATE_LABELS,
    PLUGIN_DESIRED_STATE_LABELS,
    PLUGIN_HEALTH_LABELS,
    PLUGIN_OBSERVED_STATE_LABELS,
    pluginDatabaseStateTone,
    pluginHealthTone,
    pluginObservedStateTone,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { PluginBackupsComponent } from '../plugin-backups/plugin-backups.component';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';

/** How often the panel asks for the runtime while it is shown. */
export const PLUGIN_RUNTIME_POLL_MS = 5000;

const BLOCKED_REASON_MESSAGES: Readonly<Record<PluginBlockedReason, string>> = {
    required_settings_missing:
        'The plugin is stopped because required settings are not set. Set them in the Settings tab and it starts.',
};

/**
 * Where a backend plugin runs and how it is doing: its node, its placement (port, UID, desired and observed state,
 * health, version, process, memory), why it is held stopped, and its last error and log lines when it failed. For a
 * plugin with a database: its state, server, names, migrations, effective limits, size, last error, and when the
 * platform last set the statement timeout back, and its backups. For a plugin with a backend: the hosts it may reach
 * on the internet. While an upgrade has the node run the new version, "Running 0.6.0 → 0.7.0".
 *
 * Polls the runtime every few seconds while it is shown (not while the browser tab is hidden) and stops when it is
 * destroyed. Restart asks for confirmation first.
 */
@Component({
    selector: 'app-plugin-runtime-panel',
    imports: [
        ButtonComponent,
        DatePipe,
        DecimalPipe,
        LoadingSpinnerComponent,
        PluginBackupsComponent,
        PluginBadgeComponent,
    ],
    templateUrl: './plugin-runtime-panel.component.html',
    styleUrl: './plugin-runtime-panel.component.scss',
})
export class PluginRuntimePanelComponent {
    readonly identifier = input.required<string>();
    readonly pluginName = input.required<string>();
    /** The plugin's open upgrade: the backups follow its stage, failure and restore. */
    readonly openUpgrade = input<PluginUpgrade | null>(null);
    /** "Restore backup…" was chosen: the backups come into view. */
    readonly revealBackups = input(false);
    /**
     * The process moved (observed state or health changed, a restart or a restore was asked for), so the plugin's
     * state may have.
     */
    readonly runtimeChanged = output<void>();

    protected readonly runtime = signal<PluginRuntimeResponse | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<PluginErrorView | null>(null);
    protected readonly isRestarting = signal(false);
    protected readonly node = computed(() => this.runtime()?.node ?? null);
    protected readonly placement = computed(() => this.runtime()?.placement ?? null);
    protected readonly observedLabel = computed(() => {
        const placement = this.placement();
        return placement ? PLUGIN_OBSERVED_STATE_LABELS[placement.observed_state] : '';
    });
    protected readonly observedTone = computed(() => {
        const placement = this.placement();
        return placement ? pluginObservedStateTone(placement.observed_state) : 'neutral';
    });
    protected readonly healthLabel = computed(() => {
        const placement = this.placement();
        return placement ? PLUGIN_HEALTH_LABELS[placement.health] : '';
    });
    protected readonly healthTone = computed(() => {
        const placement = this.placement();
        return placement ? pluginHealthTone(placement.health) : 'neutral';
    });
    protected readonly desiredLabel = computed(() => {
        const placement = this.placement();
        return placement ? PLUGIN_DESIRED_STATE_LABELS[placement.desired_state] : '';
    });
    protected readonly blockedMessage = computed(() => {
        const reason = this.placement()?.blocked_reason ?? null;
        return reason ? BLOCKED_REASON_MESSAGES[reason] : null;
    });
    protected readonly logText = computed(() => this.placement()?.log_tail.join('\n') ?? '');
    /** `null` hides the section: the current package has no database. */
    protected readonly database = computed(() => {
        const database = this.runtime()?.database ?? null;
        if (!database) return null;
        return {
            ...database,
            stateLabel: PLUGIN_DATABASE_STATE_LABELS[database.state],
            stateTone: pluginDatabaseStateTone(database.state),
            serverLabel: `${database.server.name} (${database.server.host}:${database.server.port})`,
            migrationsCount: `${database.migrations.applied.length} of ${database.migrations.in_package}`,
            size: database.size_bytes === null ? null : formatFileSize(database.size_bytes, 'auto'),
        };
    });
    /** `null` hides the section: the plugin has no backend. */
    protected readonly egress = computed(() => this.runtime()?.egress ?? null);
    /** "Running 0.6.0 → 0.7.0" while the node runs the upgrade's target; `null` otherwise. */
    protected readonly upgradeText = computed(() => {
        const upgrade = this.runtime()?.upgrade ?? null;
        return upgrade ? `Running ${upgrade.from_version} → ${upgrade.to_version}` : null;
    });
    /** Changes whenever what the backups allow may have changed. */
    protected readonly backupsRefreshKey = computed(() => {
        const upgrade = this.openUpgrade();
        if (!upgrade) return 'none';
        const restore = upgrade.restore;
        return [upgrade.id, upgrade.stage, upgrade.failed, upgrade.backup_id, restore?.id, restore?.state].join('|');
    });

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);
    private readonly document = inject(DOCUMENT);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        toObservable(this.identifier)
            .pipe(
                switchMap((identifier) =>
                    timer(0, PLUGIN_RUNTIME_POLL_MS).pipe(
                        filter(() => !this.document.hidden),
                        // A slow answer is never overtaken by the next poll.
                        exhaustMap(() =>
                            this.storage.getRuntime(identifier).pipe(
                                catchError((error: unknown) => {
                                    this.loadError.set(toPluginErrorView(error, "Couldn't load the runtime."));
                                    return EMPTY;
                                }),
                                finalize(() => this.isLoading.set(false))
                            )
                        )
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((runtime) => {
                if (this.show(runtime)) this.runtimeChanged.emit();
            });
    }

    protected restart(): void {
        if (this.isRestarting()) return;
        const identifier = this.identifier();
        const name = this.pluginName();
        this.confirmation
            .confirm({
                title: 'Restart the plugin?',
                message: `${escapeHtml(name)} stops and starts again. Requests it is answering now fail.`,
                type: 'warning',
                confirmText: 'Restart',
                cancelText: 'Cancel',
            })
            .pipe(
                filter((answer) => answer === true),
                switchMap(() => {
                    this.isRestarting.set(true);
                    return this.storage.restart(identifier).pipe(finalize(() => this.isRestarting.set(false)));
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (runtime) => {
                    this.show(runtime);
                    this.toast.success(`${name} is restarting.`);
                    this.runtimeChanged.emit();
                },
                error: (error: unknown) =>
                    this.toast.error(toPluginErrorView(error, "Couldn't restart the plugin.").message),
            });
    }

    /** Shows the runtime; `true` when the process moved since the last one shown (observed state or health). */
    private show(runtime: PluginRuntimeResponse): boolean {
        const previous = this.runtime()?.placement ?? null;
        const next = runtime.placement;
        this.runtime.set(runtime);
        this.loadError.set(null);
        return (
            previous !== null &&
            next !== null &&
            (previous.observed_state !== next.observed_state || previous.health !== next.health)
        );
    }
}
