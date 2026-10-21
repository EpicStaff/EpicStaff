import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { Component, computed, inject, signal, WritableSignal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { ButtonComponent, LoadingSpinnerComponent, SelectComponent, SelectItem } from '@shared/components';
import { catchError, finalize, of, switchMap, tap } from 'rxjs';

import {
    PLUGIN_ACTIVITY_PAGE_SIZE,
    PluginActivityListComponent,
} from '../../components/plugin-activity-list/plugin-activity-list.component';
import { PluginServiceAccountCardComponent } from '../../components/plugin-service-account-card/plugin-service-account-card.component';
import { OrganizationServiceAccount, PluginActivityEvent } from '../../models/plugin-activity.model';
import { PluginActivityApiService } from '../../services/plugin-activity-api.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

const ALL_PLUGINS_LABEL = 'All plugins';

/**
 * Settings → Plugin activity (`/settings/plugin-activity`): the plugins with a backend acting in the active
 * organization with the access they declared, and what plugins did in it, newest first. Holders of `audit: read`
 * only; the endpoints say 403 to anyone else, which the page shows instead of both sections.
 */
@Component({
    selector: 'app-plugin-activity-settings-page',
    imports: [
        ButtonComponent,
        LoadingSpinnerComponent,
        PluginActivityListComponent,
        PluginServiceAccountCardComponent,
        SelectComponent,
    ],
    templateUrl: './plugin-activity-settings-page.component.html',
    styleUrl: './plugin-activity-settings-page.component.scss',
})
export class PluginActivitySettingsPageComponent {
    protected readonly accounts = signal<OrganizationServiceAccount[]>([]);
    protected readonly isLoadingAccounts = signal(true);
    protected readonly accountsError = signal<string | null>(null);
    protected readonly events = signal<PluginActivityEvent[]>([]);
    protected readonly count = signal(0);
    protected readonly page = signal(1);
    protected readonly pluginFilter = signal<string | null>(null);
    protected readonly isLoadingEvents = signal(true);
    protected readonly eventsError = signal<string | null>(null);
    /** Either endpoint refused the caller: their role lacks `audit: read` in this organization. */
    protected readonly isForbidden = signal(false);
    protected readonly pluginItems = computed<SelectItem[]>(() => [
        { name: ALL_PLUGINS_LABEL, value: null },
        ...this.accounts().map((account) => ({ name: account.plugin.name, value: account.plugin.identifier })),
    ]);
    protected readonly emptyMessage = computed(() =>
        this.pluginFilter() === null
            ? 'No plugin has done anything in this organization yet.'
            : 'This plugin has done nothing in this organization yet.'
    );
    private readonly accountReloads = signal(0);
    private readonly eventReloads = signal(0);
    private readonly eventRequest = computed(() => ({
        plugin: this.pluginFilter(),
        page: this.page(),
        reload: this.eventReloads(),
    }));

    protected readonly allPluginsLabel = ALL_PLUGINS_LABEL;
    protected readonly pageSize = PLUGIN_ACTIVITY_PAGE_SIZE;

    private readonly api = inject(PluginActivityApiService);

    constructor() {
        toObservable(this.accountReloads)
            .pipe(
                tap(() => {
                    this.isLoadingAccounts.set(true);
                    this.accountsError.set(null);
                }),
                switchMap(() =>
                    this.api.listOrganizationServiceAccounts().pipe(
                        catchError((error: unknown) => {
                            this.onFailure(error, this.accountsError, "Couldn't load the plugins.");
                            return of(null);
                        }),
                        finalize(() => this.isLoadingAccounts.set(false))
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((accounts) => {
                if (accounts) this.accounts.set(accounts);
            });

        toObservable(this.eventRequest)
            .pipe(
                tap(() => {
                    this.isLoadingEvents.set(true);
                    this.eventsError.set(null);
                }),
                switchMap(({ plugin, page }) =>
                    this.api.listOrganizationActivity({ page, pageSize: PLUGIN_ACTIVITY_PAGE_SIZE, plugin }).pipe(
                        catchError((error: unknown) => {
                            this.onFailure(error, this.eventsError, "Couldn't load the activity.");
                            this.clearEvents();
                            return of(null);
                        }),
                        finalize(() => this.isLoadingEvents.set(false))
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((response) => {
                if (!response) return;
                this.events.set(response.results);
                this.count.set(response.count);
            });
    }

    protected onPluginChange(value: unknown): void {
        this.pluginFilter.set(typeof value === 'string' ? value : null);
        this.page.set(1);
        // The old plugin's events must not stand under the new filter while it loads.
        this.clearEvents();
    }

    protected onPageChange(page: number): void {
        this.page.set(page);
    }

    protected reloadAccounts(): void {
        this.accountReloads.update((count) => count + 1);
    }

    protected reloadEvents(): void {
        this.eventReloads.update((count) => count + 1);
    }

    private clearEvents(): void {
        this.events.set([]);
        this.count.set(0);
    }

    /** A 403 hides the whole page behind its explanation; any other failure shows in the section that failed. */
    private onFailure(error: unknown, message: WritableSignal<string | null>, fallback: string): void {
        if (error instanceof HttpErrorResponse && error.status === HttpStatusCode.Forbidden) {
            this.isForbidden.set(true);
            return;
        }
        message.set(toPluginErrorView(error, fallback).message);
    }
}
