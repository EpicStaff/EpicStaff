import { DatePipe, DOCUMENT } from '@angular/common';
import { Component, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    CheckboxComponent,
    LoadingSpinnerComponent,
    PaginationControlsComponent,
    TableRow,
} from '@shared/components';
import { catchError, EMPTY, expand, filter, of, switchMap, take, tap, timer } from 'rxjs';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { PluginOrgRemovedJob, PluginState } from '../../models/plugin-admin.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    PLUGIN_DATA_REMOVAL_STATE_LABELS,
    PluginBadgeTone,
    pluginDataRemovalOrganizationText,
    pluginDataRemovalStateTone,
} from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';
import { PluginDataRemovalActionsComponent } from '../plugin-data-removal-actions/plugin-data-removal-actions.component';

export const PLUGIN_DATA_REMOVALS_PAGE_SIZE = 20;

/** How often the list asks again while one of its data removals waits or runs. */
export const PLUGIN_DATA_REMOVALS_POLL_MS = 10_000;

const COLUMNS: AppTableColumnDef[] = [
    { key: 'organization', label: 'Organization', width: 'minmax(160px, 2fr)' },
    { key: 'state', label: 'State', width: 'minmax(100px, 1fr)' },
    { key: 'attempts', label: 'Attempts', width: 'minmax(90px, 0.8fr)' },
    { key: 'nextTry', label: 'Next try', width: 'minmax(140px, 1.2fr)' },
    { key: 'error', label: 'Error', width: 'minmax(200px, 2.5fr)' },
    { key: 'actions', label: 'Actions', width: 'minmax(150px, 1.2fr)', align: 'end' },
];

/**
 * "Deleted organizations": the data removals (runs of the plugin's organization removed hook) of organizations deleted
 * while they had the plugin, a page at a time, newest first. Open ones by default; "Show finished" adds those done or
 * skipped. Each shows the organization's name as it was, its state, attempts, next try and error, with Retry and Skip
 * as the job allows. While one waits or runs, or while the plugin is being deleted (which gives up on failed ones by
 * itself), the list asks again every few seconds (not while the browser tab is hidden); a new page, the toggle, a
 * change of the plugin's state or an action restarts loading and polling, so an older answer never overwrites a newer
 * one.
 */
@Component({
    selector: 'app-plugin-data-removals',
    imports: [
        AppTableCellDirective,
        AppTableComponent,
        ButtonComponent,
        CheckboxComponent,
        DatePipe,
        LoadingSpinnerComponent,
        MatTooltip,
        PaginationControlsComponent,
        PluginBadgeComponent,
        PluginDataRemovalActionsComponent,
    ],
    templateUrl: './plugin-data-removals.component.html',
    styleUrl: './plugin-data-removals.component.scss',
})
export class PluginDataRemovalsComponent {
    readonly identifier = input.required<string>();
    readonly pluginName = input.required<string>();
    /** While the plugin is being deleted, failed removals are skipped by the platform: the list keeps asking. */
    readonly pluginState = input<PluginState | null>(null);

    protected readonly page = signal(1);
    protected readonly showFinished = signal(false);
    protected readonly jobs = signal<PluginOrgRemovedJob[]>([]);
    protected readonly count = signal(0);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<string | null>(null);
    protected readonly rows = computed<TableRow[]>(() => this.jobs().map((job) => ({ id: job.id })));
    protected readonly emptyMessage = computed(() =>
        this.showFinished()
            ? `No organization was deleted while it had ${this.pluginName()}.`
            : `No data removal of a deleted organization is waiting.`
    );
    private readonly jobsById = computed(() => new Map(this.jobs().map((job) => [job.id, job])));
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({
        identifier: this.identifier(),
        page: this.page(),
        showFinished: this.showFinished(),
        pluginState: this.pluginState(),
        reload: this.reloads(),
    }));

    protected readonly columns = COLUMNS;
    protected readonly pageSize = PLUGIN_DATA_REMOVALS_PAGE_SIZE;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly document = inject(DOCUMENT);

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => {
                    this.isLoading.set(true);
                    this.loadError.set(null);
                }),
                switchMap(({ identifier, page, showFinished, pluginState }) => {
                    const fetchPage = () =>
                        this.storage
                            .listOrgRemovedJobs(identifier, {
                                state: showFinished ? 'all' : 'open',
                                deletedOrganizations: true,
                                page,
                                pageSize: PLUGIN_DATA_REMOVALS_PAGE_SIZE,
                            })
                            .pipe(
                                catchError((error: unknown) => {
                                    this.loadError.set(
                                        toPluginErrorView(error, "Couldn't load the data removals.").message
                                    );
                                    return of(null);
                                })
                            );
                    // The next poll, at the first tick the browser tab is shown; it waits for the previous answer.
                    const nextPoll = () =>
                        timer(PLUGIN_DATA_REMOVALS_POLL_MS, PLUGIN_DATA_REMOVALS_POLL_MS).pipe(
                            filter(() => !this.document.hidden),
                            take(1),
                            switchMap(fetchPage)
                        );
                    return fetchPage().pipe(
                        tap(() => this.isLoading.set(false)),
                        // After a failed answer the rows shown decide, so one failure does not stop the polling.
                        expand((response) =>
                            pluginState === 'purging' || isUnderWay(response?.results ?? this.jobs())
                                ? nextPoll()
                                : EMPTY
                        )
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

    protected jobOf(row: TableRow): PluginOrgRemovedJob | undefined {
        return this.jobsById().get(row['id'] as number);
    }

    protected organizationText(job: PluginOrgRemovedJob): string {
        return pluginDataRemovalOrganizationText(job);
    }

    protected stateLabel(job: PluginOrgRemovedJob): string {
        return PLUGIN_DATA_REMOVAL_STATE_LABELS[job.state];
    }

    protected stateTone(job: PluginOrgRemovedJob): PluginBadgeTone {
        return pluginDataRemovalStateTone(job.state);
    }

    /** The next try only while one is planned. */
    protected nextTryOf(job: PluginOrgRemovedJob): string | null {
        return job.state === 'pending' ? job.next_attempt_at : null;
    }

    protected onShowFinishedChange(checked: boolean): void {
        this.showFinished.set(checked);
        this.page.set(1);
        // The old filter's jobs must not stand under the new one while it loads.
        this.show({ count: 0, next: null, previous: null, results: [] });
    }

    protected onPageChange(page: number): void {
        this.page.set(page);
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    private show(response: ApiGetRequest<PluginOrgRemovedJob>): void {
        this.jobs.set(response.results);
        this.count.set(response.count);
    }
}

function isUnderWay(jobs: readonly PluginOrgRemovedJob[]): boolean {
    return jobs.some((job) => job.state === 'pending' || job.state === 'running');
}
