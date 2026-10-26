import { Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { ButtonComponent, SelectComponent, SelectItem } from '@shared/components';
import { GetOrganizationResponse } from '@shared/models';
import { catchError, finalize, of, switchMap, tap } from 'rxjs';

import { AdminOrganizationsService } from '../../../role-base-access/services/admin/organizations.service';
import { PluginActivityEvent } from '../../models/plugin-activity.model';
import { PluginActivityApiService } from '../../services/plugin-activity-api.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { fetchAllOrganizations } from '../../utils/plugin-organizations.util';
import {
    PLUGIN_ACTIVITY_PAGE_SIZE,
    PluginActivityListComponent,
} from '../plugin-activity-list/plugin-activity-list.component';

const ALL_ORGANIZATIONS_LABEL = 'All organizations';

/**
 * One plugin's activity for a SuperAdmin: every organization's events and those of the whole deployment, newest
 * first, optionally narrowed to one organization.
 */
@Component({
    selector: 'app-plugin-admin-activity',
    imports: [ButtonComponent, PluginActivityListComponent, SelectComponent],
    templateUrl: './plugin-admin-activity.component.html',
    styleUrl: './plugin-admin-activity.component.scss',
})
export class PluginAdminActivityComponent implements OnInit {
    readonly identifier = input.required<string>();

    protected readonly events = signal<PluginActivityEvent[]>([]);
    protected readonly count = signal(0);
    protected readonly page = signal(1);
    protected readonly organizationId = signal<number | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly organizations = signal<GetOrganizationResponse[]>([]);
    protected readonly isLoadingOrganizations = signal(true);
    protected readonly organizationItems = computed<SelectItem[]>(() => [
        { name: ALL_ORGANIZATIONS_LABEL, value: null },
        ...this.organizations().map((organization) => ({ name: organization.name, value: organization.id })),
    ]);
    protected readonly emptyMessage = computed(() =>
        this.organizationId() === null
            ? 'Nothing has happened with this plugin yet.'
            : 'Nothing has happened with this plugin in this organization yet.'
    );
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({
        identifier: this.identifier(),
        organizationId: this.organizationId(),
        page: this.page(),
        reload: this.reloads(),
    }));

    protected readonly allOrganizationsLabel = ALL_ORGANIZATIONS_LABEL;
    protected readonly pageSize = PLUGIN_ACTIVITY_PAGE_SIZE;

    private readonly activityApi = inject(PluginActivityApiService);
    private readonly organizationsApi = inject(AdminOrganizationsService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => {
                    this.isLoading.set(true);
                    this.loadError.set(null);
                }),
                switchMap(({ identifier, organizationId, page }) =>
                    this.activityApi
                        .listPluginActivity(identifier, { page, pageSize: PLUGIN_ACTIVITY_PAGE_SIZE, organizationId })
                        .pipe(
                            catchError((error: unknown) => {
                                this.loadError.set(toPluginErrorView(error, "Couldn't load the activity.").message);
                                this.clearEvents();
                                return of(null);
                            }),
                            finalize(() => this.isLoading.set(false))
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

    ngOnInit(): void {
        // The filter is optional: without the organization list the activity still shows, unfiltered.
        fetchAllOrganizations(this.organizationsApi)
            .pipe(
                finalize(() => this.isLoadingOrganizations.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (organizations) => this.organizations.set(organizations),
                error: () => undefined,
            });
    }

    protected onOrganizationChange(value: unknown): void {
        this.organizationId.set(typeof value === 'number' ? value : null);
        this.page.set(1);
        // The old organization's events must not stand under the new filter while it loads.
        this.clearEvents();
    }

    protected onPageChange(page: number): void {
        this.page.set(page);
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    private clearEvents(): void {
        this.events.set([]);
        this.count.set(0);
    }
}
