import { DatePipe, DOCUMENT } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
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
import { PluginGrant, PluginGrantAction } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    PLUGIN_GRANT_ACTION_LABELS,
    PLUGIN_GRANT_STATE_LABELS,
    PluginBadgeTone,
    pluginGrantStateTone,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';

export const PLUGIN_GRANTS_PAGE_SIZE = 20;

/** How often the table asks again while an install hook runs in one of its rows. */
export const PLUGIN_GRANTS_POLL_MS = 5000;

const COLUMNS: AppTableColumnDef[] = [
    { key: 'organization', label: 'Organization', width: 'minmax(160px, 2fr)' },
    { key: 'state', label: 'State', width: 'minmax(200px, 2.5fr)' },
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
};

/** A grant action that asks for confirmation, then sends one request answering with the grant. */
interface ConfirmedGrantAction {
    confirmation: ConfirmationDialogData;
    request: () => Observable<PluginGrant>;
    successMessage: string;
    /** Whether the plugin's count of active grants may have changed (the page reloads the plugin). */
    changesActiveCount: boolean;
    failureFallback: string;
}

/**
 * The organizations a plugin is granted to, a page at a time, and the Grant action.
 *
 * A grant whose install hook runs shows "Installing…" ("Waiting for the plugin to start" until the plugin claims the
 * hook), and the table asks for its page again every few seconds (not while the browser tab is hidden) until no row
 * installs any more. Loads and polls are one pipeline: a new page or a reload (after a grant or a lifecycle action)
 * restarts it, so an answer still on its way never overwrites a newer one. A failed install shows the hook's error; a
 * suspended grant shows since when and until when its data is kept.
 *
 * A row's buttons are exactly the grant's `allowed_actions`, in the server's order: the server owns the state machine.
 * "Suspend…" opens the suspend preview; "Resume" and "Retry install" ask for confirmation first.
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
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({
        identifier: this.identifier(),
        page: this.page(),
        reload: this.reloads(),
    }));

    protected readonly columns = COLUMNS;
    protected readonly pageSize = PLUGIN_GRANTS_PAGE_SIZE;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly dialogs = inject(PluginDialogsService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);
    private readonly document = inject(DOCUMENT);
    private readonly destroyRef = inject(DestroyRef);
    /** One handler per action, so a new action does not build until it has one. */
    private readonly actionHandlers: Readonly<Record<PluginGrantAction, (grant: PluginGrant) => void>> = {
        suspend: (grant) => this.openSuspend(grant),
        resume: (grant) => this.resume(grant),
        retry_install: (grant) => this.retryInstall(grant),
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
                        expand((response) => (isInstalling(response?.results ?? this.grants()) ? nextPoll() : EMPTY))
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
        return PLUGIN_GRANT_STATE_LABELS[grant.state];
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
            successMessage: `${pluginName} is resumed in ${organizationName}.`,
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
            request: () => this.storage.retryInstallHook(this.identifier(), grant.id),
            successMessage: `${pluginName} is installing in ${organizationName} again.`,
            failureFallback: "Couldn't retry the install.",
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
                    this.toast.success(run.successMessage);
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

    /** Shows a page of grants; tells the page when a grant on it changed state since the last time it was shown. */
    private show(response: ApiGetRequest<PluginGrant>): void {
        const previous = this.grantsById();
        const stateChanged = response.results.some((grant) => {
            const shown = previous.get(grant.id);
            return shown !== undefined && shown.state !== grant.state;
        });
        this.grants.set(response.results);
        this.count.set(response.count);
        if (stateChanged) this.grantsChanged.emit();
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

function isInstalling(grants: readonly PluginGrant[]): boolean {
    return grants.some((grant) => grant.state === 'granting');
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
