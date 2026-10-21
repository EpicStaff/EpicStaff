import { DatePipe, DOCUMENT } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    ConfirmationDialogService,
    LoadingSpinnerComponent,
    PaginationControlsComponent,
    Spinner2Component,
    TableRow,
} from '@shared/components';
import { escapeHtml, getRelativeTime } from '@shared/utils';
import { catchError, EMPTY, expand, filter, finalize, of, switchMap, take, tap, timer } from 'rxjs';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ToastService } from '../../../../services/notifications';
import { PluginGrant } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { PLUGIN_GRANT_STATE_LABELS, PluginBadgeTone, pluginGrantStateTone } from '../../utils/plugin-display.util';
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
];

/**
 * The organizations a plugin is granted to, a page at a time, and the Grant action.
 *
 * A grant whose install hook runs shows "Installing…", and the table asks for its page again every few seconds (not
 * while the browser tab is hidden) until no row installs any more. Loads and polls are one pipeline: a new page or a
 * reload (after a grant or a retry) restarts it, so an answer still on its way never overwrites a newer one. A failed
 * install shows the hook's error and "Retry install", which asks for confirmation first.
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
    /** The grants whose retry request is under way. */
    protected readonly retryingIds = signal<ReadonlySet<number>>(new Set());
    protected readonly rows = computed<TableRow[]>(() => this.grants().map((grant) => ({ id: grant.id })));
    private readonly grantsById = computed(() => new Map(this.grants().map((grant) => [grant.id, grant])));
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

    /** The install hook's own error; the grant's copy of it when the job has none. */
    protected installError(grant: PluginGrant): string {
        return grant.install_hook?.error ?? grant.last_hook_error ?? 'The install hook failed.';
    }

    protected keyLastUsed(grant: PluginGrant): string {
        const lastUsed = grant.service_account?.key_last_used_at ?? null;
        return lastUsed === null ? 'Key never used' : `Key used ${getRelativeTime(lastUsed)}`;
    }

    protected isRetrying(grant: PluginGrant): boolean {
        return this.retryingIds().has(grant.id);
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

    protected retryInstall(grant: PluginGrant): void {
        if (this.isRetrying(grant)) return;
        const identifier = this.identifier();
        const pluginName = this.pluginName();
        const organizationName = grant.organization.name;
        this.confirmation
            .confirm({
                title: 'Retry the install?',
                message: `${escapeHtml(pluginName)} runs its install hook in ${escapeHtml(organizationName)} again.`,
                type: 'warning',
                confirmText: 'Retry install',
                cancelText: 'Cancel',
            })
            .pipe(
                filter((answer) => answer === true),
                switchMap(() => {
                    this.setRetrying(grant.id, true);
                    return this.storage
                        .retryInstallHook(identifier, grant.id)
                        .pipe(finalize(() => this.setRetrying(grant.id, false)));
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (updated) => {
                    this.replaceGrant(updated);
                    this.toast.success(`${pluginName} is installing in ${organizationName} again.`);
                    // Restarts loading and polling: a poll that was on its way must not bring the failure back.
                    this.reload();
                },
                error: (error: unknown) => {
                    this.toast.error(toPluginErrorView(error, "Couldn't retry the install.").message);
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

    private setRetrying(grantId: number, retrying: boolean): void {
        this.retryingIds.update((ids) => {
            const next = new Set(ids);
            if (retrying) next.add(grantId);
            else next.delete(grantId);
            return next;
        });
    }
}

function isInstalling(grants: readonly PluginGrant[]): boolean {
    return grants.some((grant) => grant.state === 'granting');
}
