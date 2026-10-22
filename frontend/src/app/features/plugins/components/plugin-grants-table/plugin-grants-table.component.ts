import { DatePipe, DOCUMENT } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, LOCALE_ID, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    ConfirmationDialogData,
    ConfirmationDialogService,
    LoadingSpinnerComponent,
    PaginationControlsComponent,
    Spinner2Component,
    TableRow,
} from '@shared/components';
import { escapeHtml, getRelativeTime } from '@shared/utils';
import { catchError, EMPTY, expand, filter, finalize, Observable, of, switchMap, take, tap, timer } from 'rxjs';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ToastService } from '../../../../services/notifications';
import { PluginGrant, PluginGrantAction, PluginState } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    PLUGIN_GRANT_ACTION_LABELS,
    PluginBadgeTone,
    PluginDataRemovalLine,
    pluginDataRemovalLine,
    pluginGrantStateLabel,
    pluginGrantStateTone,
    pluginRetryProgress,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';
import { PluginDataRemovalActionsComponent } from '../plugin-data-removal-actions/plugin-data-removal-actions.component';

export const PLUGIN_GRANTS_PAGE_SIZE = 20;

/** How often the table asks again while one of its rows installs, upgrades or deletes its data. */
export const PLUGIN_GRANTS_POLL_MS = 5000;

const COLUMNS: AppTableColumnDef[] = [
    { key: 'organization', label: 'Organization', width: 'minmax(160px, 2fr)' },
    { key: 'state', label: 'State', width: 'minmax(200px, 2.5fr)' },
    { key: 'version', label: 'Version', width: 'minmax(80px, 0.7fr)' },
    { key: 'serviceAccount', label: 'Service account', width: 'minmax(170px, 2fr)' },
    { key: 'ownedResources', label: 'Owned resources', width: 'minmax(120px, 1fr)' },
    { key: 'grantedBy', label: 'Granted by', width: 'minmax(160px, 2fr)' },
    { key: 'grantedAt', label: 'Granted', width: 'minmax(110px, 1fr)' },
    { key: 'actions', label: 'Actions', width: 'minmax(200px, 1.5fr)', align: 'end' },
];

/** A button of the Actions column. */
interface GrantActionButton {
    action: PluginGrantAction;
    label: string;
    type: 'outline-primary' | 'outline-danger';
}

const GRANT_ACTION_BUTTON_TYPES: Readonly<Record<PluginGrantAction, GrantActionButton['type']>> = {
    suspend: 'outline-danger',
    resume: 'outline-primary',
    retry_install: 'outline-primary',
    retry_upgrade: 'outline-primary',
    purge: 'outline-danger',
};

/** What the table says once a grant action went through: `warning` when the grant still needs something done. */
interface GrantActionToast {
    tone: 'success' | 'warning';
    message: string;
}

/** A grant action that asks for confirmation, then sends one request answering with the grant. */
interface ConfirmedGrantAction {
    confirmation: ConfirmationDialogData;
    request: () => Observable<PluginGrant>;
    /** The toast for the grant as the server answered with it. */
    resultToast: (updated: PluginGrant) => GrantActionToast;
    /** Whether the plugin's count of active grants may have changed (the page reloads the plugin). */
    changesActiveCount: boolean;
    failureFallback: string;
}

/**
 * The organizations a plugin is granted to, a page at a time, and the Grant action.
 *
 * A grant whose install hook runs shows "Installing…" ("Waiting for the plugin to start" until the plugin claims the
 * hook); one being upgraded shows "Upgrading…" with its upgrade hook's attempt, next try and last error; a grant whose
 * data is being deleted shows "Deleting data…", where the plugin is with deleting its own data (with Retry and Skip as
 * that job allows), and what EpicStaff could not delete yet. The Version column is the version each organization was
 * last brought to. The table asks for its page again every few seconds (not while the browser tab is hidden) until no
 * row installs, upgrades or deletes any more. Loads and polls
 * are one pipeline: a new page, a reload (after a grant or a lifecycle action) or a change of the plugin's state
 * (which changes what every grant allows) restarts it, so an answer still on its way never overwrites a newer one. A
 * failed install or upgrade shows the hook's error; a suspended grant shows since when and until when its data is kept.
 *
 * A row's buttons are exactly the grant's `allowed_actions`, in the server's order: the server owns the state machine.
 * "Suspend…" and "Delete data…" open their previews; "Resume", "Retry install" and "Retry upgrade" ask for
 * confirmation first.
 */
@Component({
    selector: 'app-plugin-grants-table',
    imports: [
        AppTableCellDirective,
        AppTableComponent,
        ButtonComponent,
        DatePipe,
        LoadingSpinnerComponent,
        MatTooltip,
        PaginationControlsComponent,
        PluginBadgeComponent,
        PluginDataRemovalActionsComponent,
        Spinner2Component,
    ],
    templateUrl: './plugin-grants-table.component.html',
    styleUrl: './plugin-grants-table.component.scss',
})
export class PluginGrantsTableComponent {
    readonly identifier = input.required<string>();
    readonly pluginName = input.required<string>();
    /** Only a running plugin can be granted. */
    readonly canGrant = input(false);
    /** What each grant allows depends on the plugin's state too, so the grants are loaded again when it changes. */
    readonly pluginState = input<PluginState | null>(null);
    /** A grant was made or changed state here, so the plugin's count of active grants may have changed. */
    readonly grantsChanged = output<void>();

    protected readonly page = signal(1);
    protected readonly grants = signal<PluginGrant[]>([]);
    protected readonly count = signal(0);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<string | null>(null);
    /** The grants with an action request under way; their buttons wait. */
    protected readonly busyIds = signal<ReadonlySet<number>>(new Set());
    protected readonly rows = computed<TableRow[]>(() => this.grants().map((grant) => ({ id: grant.id })));
    private readonly grantsById = computed(() => new Map(this.grants().map((grant) => [grant.id, grant])));
    private readonly actionButtonsById = computed(
        () => new Map(this.grants().map((grant) => [grant.id, toActionButtons(grant)] as const))
    );
    private readonly dataRemovalsById = computed(() => {
        const pluginName = this.pluginName();
        const lines = new Map<number, PluginDataRemovalLine>();
        for (const grant of this.grants()) {
            const line =
                grant.state === 'purging'
                    ? pluginDataRemovalLine(grant.org_removed_hook, pluginName, this.locale)
                    : null;
            if (line) lines.set(grant.id, line);
        }
        return lines;
    });
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({
        identifier: this.identifier(),
        page: this.page(),
        pluginState: this.pluginState(),
        reload: this.reloads(),
    }));

    protected readonly columns = COLUMNS;
    protected readonly pageSize = PLUGIN_GRANTS_PAGE_SIZE;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly dialogs = inject(PluginDialogsService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);
    private readonly document = inject(DOCUMENT);
    private readonly locale = inject(LOCALE_ID);
    private readonly destroyRef = inject(DestroyRef);
    /** One handler per action, so a new action does not build until it has one. */
    private readonly actionHandlers: Readonly<Record<PluginGrantAction, (grant: PluginGrant) => void>> = {
        suspend: (grant) => this.openSuspend(grant),
        resume: (grant) => this.resume(grant),
        retry_install: (grant) => this.retryInstall(grant),
        retry_upgrade: (grant) => this.retryUpgrade(grant),
        purge: (grant) => this.openPurge(grant),
    };

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => {
                    this.isLoading.set(true);
                    this.loadError.set(null);
                }),
                switchMap(({ identifier, page }) => {
                    const fetchPage = () =>
                        this.storage.listGrants(identifier, page, PLUGIN_GRANTS_PAGE_SIZE).pipe(
                            catchError((error: unknown) => {
                                this.loadError.set(toPluginErrorView(error, "Couldn't load the grants.").message);
                                return of(null);
                            })
                        );
                    // The next poll, at the first tick the browser tab is shown; it waits for the previous answer.
                    const nextPoll = () =>
                        timer(PLUGIN_GRANTS_POLL_MS, PLUGIN_GRANTS_POLL_MS).pipe(
                            filter(() => !this.document.hidden),
                            take(1),
                            switchMap(fetchPage)
                        );
                    return fetchPage().pipe(
                        tap(() => this.isLoading.set(false)),
                        // After a failed answer the rows shown decide, so one failure does not stop the polling.
                        expand((response) => (needsPolling(response?.results ?? this.grants()) ? nextPoll() : EMPTY))
                    );
                }),
                takeUntilDestroyed()
            )
            .subscribe((response) => {
                if (!response) return;
                this.loadError.set(null);
                this.show(response);
            });
    }

    protected grantOf(row: TableRow): PluginGrant | undefined {
        return this.grantsById().get(row['id'] as number);
    }

    protected stateLabel(grant: PluginGrant): string {
        return pluginGrantStateLabel(grant);
    }

    protected stateTone(grant: PluginGrant): PluginBadgeTone {
        return pluginGrantStateTone(grant.state);
    }

    /**
     * A pending install waits for the plugin process to start and claim it, which may take long when the plugin is
     * down, so it does not read as installing.
     */
    protected installProgress(grant: PluginGrant): string {
        return grant.install_hook?.state === 'pending' ? 'Waiting for the plugin to start' : 'Installing…';
    }

    /** The install hook's own error; the grant's copy of it when the job has none. */
    protected installError(grant: PluginGrant): string {
        return grant.install_hook?.error ?? grant.last_hook_error ?? 'The install hook failed.';
    }

    /**
     * Where an upgrading organization is: its upgrade hook's attempt and next try while it waits or runs. The latest
     * upgrade hook may be an earlier upgrade's; then the organization waits for the new version to start.
     */
    protected upgradeProgress(grant: PluginGrant): string {
        const hook = grant.upgrade_hook;
        if (hook?.state === 'running')
            return hook.attempt > 1 ? `Attempt ${hook.attempt} running` : 'Running its upgrade';
        if (hook?.state !== 'pending') return 'Waiting for the new version to start';
        return pluginRetryProgress(hook, this.locale) ?? 'Waiting for the plugin to start';
    }

    /** The error of the attempt that failed while the upgrade hook tries again by itself; else `null`. */
    protected upgradeRetryError(grant: PluginGrant): string | null {
        const hook = grant.upgrade_hook;
        return hook?.state === 'pending' && hook.attempt > 0 ? hook.error : null;
    }

    /** The upgrade hook's own error; the grant's copy of it when the job has none. */
    protected upgradeError(grant: PluginGrant): string {
        const hook = grant.upgrade_hook;
        return (hook?.state === 'failed' ? hook.error : null) ?? grant.last_hook_error ?? 'The upgrade hook failed.';
    }

    /** Where the plugin is with deleting its own data for a deleting grant; `null` when it has nothing to delete. */
    protected dataRemovalOf(grant: PluginGrant): PluginDataRemovalLine | null {
        return this.dataRemovalsById().get(grant.id) ?? null;
    }

    protected keyLastUsed(grant: PluginGrant): string {
        const lastUsed = grant.service_account?.key_last_used_at ?? null;
        return lastUsed === null ? 'Key never used' : `Key used ${getRelativeTime(lastUsed)}`;
    }

    protected actionButtonsOf(grant: PluginGrant): readonly GrantActionButton[] {
        return this.actionButtonsById().get(grant.id) ?? [];
    }

    protected isBusy(grant: PluginGrant): boolean {
        return this.busyIds().has(grant.id);
    }

    protected runAction(grant: PluginGrant, action: PluginGrantAction): void {
        if (this.isBusy(grant)) return;
        this.actionHandlers[action](grant);
    }

    protected onPageChange(page: number): void {
        this.page.set(page);
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    protected openGrant(): void {
        this.dialogs
            .openGrant({ identifier: this.identifier(), name: this.pluginName() })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((grant) => {
                if (!grant) return;
                const message =
                    grant.state === 'granting'
                        ? `${this.pluginName()} is installing in ${grant.organization.name}.`
                        : `${this.pluginName()} is granted to ${grant.organization.name}.`;
                this.toast.success(message);
                this.grantsChanged.emit();
                this.reload();
            });
    }

    private openSuspend(grant: PluginGrant): void {
        const pluginName = this.pluginName();
        this.dialogs
            .openSuspend({ identifier: this.identifier(), pluginName, grant })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((suspended) => {
                if (suspended) {
                    this.replaceGrant(suspended);
                    this.toast.success(`${pluginName} is suspended in ${grant.organization.name}.`);
                    this.grantsChanged.emit();
                }
                // Also after Cancel: the dialog may have been refused because the grant moved meanwhile.
                this.reload();
            });
    }

    private openPurge(grant: PluginGrant): void {
        const pluginName = this.pluginName();
        this.dialogs
            .openGrantPurge({ identifier: this.identifier(), pluginName, grant })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((purging) => {
                if (purging) {
                    this.replaceGrant(purging);
                    this.toast.success(`Deleting ${pluginName}'s data in ${grant.organization.name}.`);
                    this.grantsChanged.emit();
                }
                // Also after Cancel: the dialog may have been refused because the grant moved meanwhile.
                this.reload();
            });
    }

    private resume(grant: PluginGrant): void {
        const pluginName = this.pluginName();
        const organizationName = grant.organization.name;
        this.confirmAndRun(grant, {
            confirmation: {
                title: 'Resume the plugin?',
                message:
                    `Resume ${escapeHtml(pluginName)} in ${escapeHtml(organizationName)}? Its runs work again and ` +
                    'the plugin gets new keys.',
                type: 'warning',
                confirmText: 'Resume',
                cancelText: 'Cancel',
            },
            request: () => this.storage.resumeGrant(this.identifier(), grant.id),
            // A grant suspended while it was installing comes back with its install failed.
            resultToast: (updated) =>
                updated.state === 'install_failed'
                    ? {
                          tone: 'warning',
                          message: `${pluginName} is resumed in ${organizationName}; its install has not finished. Retry it.`,
                      }
                    : { tone: 'success', message: `${pluginName} is resumed in ${organizationName}.` },
            failureFallback: "Couldn't resume the plugin.",
            changesActiveCount: true,
        });
    }

    private retryInstall(grant: PluginGrant): void {
        const pluginName = this.pluginName();
        const organizationName = grant.organization.name;
        this.confirmAndRun(grant, {
            confirmation: {
                title: 'Retry the install?',
                message: `${escapeHtml(pluginName)} runs its install hook in ${escapeHtml(organizationName)} again.`,
                type: 'warning',
                confirmText: 'Retry install',
                cancelText: 'Cancel',
            },
            request: () => this.storage.retryHook(this.identifier(), grant.id),
            resultToast: () => ({
                tone: 'success',
                message: `${pluginName} is installing in ${organizationName} again.`,
            }),
            failureFallback: "Couldn't retry the install.",
            // The grant stays out of the active count until the hook succeeds.
            changesActiveCount: false,
        });
    }

    private retryUpgrade(grant: PluginGrant): void {
        const pluginName = this.pluginName();
        const organizationName = grant.organization.name;
        this.confirmAndRun(grant, {
            confirmation: {
                title: 'Retry the upgrade?',
                message: `${escapeHtml(pluginName)} runs its upgrade hook in ${escapeHtml(organizationName)} again.`,
                type: 'warning',
                confirmText: 'Retry upgrade',
                cancelText: 'Cancel',
            },
            request: () => this.storage.retryHook(this.identifier(), grant.id),
            resultToast: () => ({
                tone: 'success',
                message: `${pluginName} is upgrading in ${organizationName} again.`,
            }),
            failureFallback: "Couldn't retry the upgrade.",
            // The grant stays out of the active count until the hook succeeds.
            changesActiveCount: false,
        });
    }

    /** Asks first; then runs the request with the row's buttons waiting, and shows the grant as it is now. */
    private confirmAndRun(grant: PluginGrant, run: ConfirmedGrantAction): void {
        this.confirmation
            .confirm(run.confirmation)
            .pipe(
                filter((answer) => answer === true),
                switchMap(() => {
                    this.setBusy(grant.id, true);
                    return run.request().pipe(finalize(() => this.setBusy(grant.id, false)));
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (updated) => {
                    this.replaceGrant(updated);
                    const toast = run.resultToast(updated);
                    if (toast.tone === 'warning') this.toast.warning(toast.message);
                    else this.toast.success(toast.message);
                    if (run.changesActiveCount) this.grantsChanged.emit();
                    // Restarts loading and polling: a poll that was on its way must not bring the old state back.
                    this.reload();
                },
                error: (error: unknown) => {
                    this.toast.error(toPluginErrorView(error, run.failureFallback).message);
                    // The grant may have moved or gone meanwhile: show what it is now.
                    this.reload();
                },
            });
    }

    /**
     * Shows a page of grants; tells the page when a grant on it changed state since the last time it was shown, or a
     * grant shown deleting its data is gone (its deletion finished).
     */
    private show(response: ApiGetRequest<PluginGrant>): void {
        const previous = this.grantsById();
        const answered = new Set(response.results.map((grant) => grant.id));
        const stateChanged = response.results.some((grant) => {
            const shown = previous.get(grant.id);
            return shown !== undefined && shown.state !== grant.state;
        });
        const purgeFinished = [...previous.values()].some(
            (grant) => grant.state === 'purging' && !answered.has(grant.id)
        );
        this.grants.set(response.results);
        this.count.set(response.count);
        if (stateChanged || purgeFinished) this.grantsChanged.emit();
    }

    private replaceGrant(updated: PluginGrant): void {
        this.grants.update((grants) => grants.map((grant) => (grant.id === updated.id ? updated : grant)));
    }

    private setBusy(grantId: number, busy: boolean): void {
        this.busyIds.update((ids) => {
            const next = new Set(ids);
            if (busy) next.add(grantId);
            else next.delete(grantId);
            return next;
        });
    }
}

/** A row is installing, upgrading or deleting its data, which the server finishes on its own. */
function needsPolling(grants: readonly PluginGrant[]): boolean {
    return grants.some(
        (grant) => grant.state === 'granting' || grant.state === 'upgrading' || grant.state === 'purging'
    );
}

/** The grant's allowed actions as buttons, in the server's order; an action this page does not know is left out. */
function toActionButtons(grant: PluginGrant): GrantActionButton[] {
    return grant.allowed_actions.filter(isKnownGrantAction).map((action) => ({
        action,
        label: PLUGIN_GRANT_ACTION_LABELS[action],
        type: GRANT_ACTION_BUTTON_TYPES[action],
    }));
}

function isKnownGrantAction(action: string): action is PluginGrantAction {
    return Object.hasOwn(PLUGIN_GRANT_ACTION_LABELS, action);
}
