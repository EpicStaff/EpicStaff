import { DatePipe } from '@angular/common';
import { Component, computed, input, output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    LoadingSpinnerComponent,
    PaginationControlsComponent,
    TableRow,
} from '@shared/components';
import { getRelativeTime } from '@shared/utils';

import { PluginActivityEvent } from '../../models/plugin-activity.model';
import {
    PLUGIN_ACTIVITY_ACTION_LABELS,
    pluginActivityActorText,
    pluginActivityDetailText,
    pluginActivityErrorText,
    pluginActivityOrganizationText,
    pluginActivityPluginText,
    pluginActivityRequestLine,
    pluginActivityTargetText,
} from '../../utils/plugin-activity-display.util';

/** What the activity endpoints return per page unless asked otherwise. */
export const PLUGIN_ACTIVITY_PAGE_SIZE = 50;

/** One event as a row shows it. */
interface ActivityEntry {
    id: number;
    createdAt: string;
    relativeTime: string;
    plugin: string;
    organization: string;
    actor: string;
    action: string;
    requestLine: string | null;
    target: string | null;
    detail: string | null;
    error: string | null;
}

const WHEN_COLUMN: AppTableColumnDef = { key: 'when', label: 'When', width: 'minmax(110px, 0.8fr)' };
const PLUGIN_COLUMN: AppTableColumnDef = { key: 'plugin', label: 'Plugin', width: 'minmax(120px, 1fr)' };
const ORGANIZATION_COLUMN: AppTableColumnDef = {
    key: 'organization',
    label: 'Organization',
    width: 'minmax(140px, 1fr)',
};
const ACTOR_COLUMN: AppTableColumnDef = { key: 'actor', label: 'Actor', width: 'minmax(200px, 2fr)' };
const ACTION_COLUMN: AppTableColumnDef = { key: 'action', label: 'Action', width: 'minmax(130px, 1fr)' };
const DETAILS_COLUMN: AppTableColumnDef = { key: 'details', label: 'Details', width: 'minmax(220px, 2.5fr)' };

/**
 * A page of plugin activity, newest first: when, who (the plugin, on behalf of whom, a SuperAdmin or the platform),
 * what, and the request line, the target, the overrides a limits change left, or the error of a failure. The container
 * loads the pages; this list only asks for another one.
 */
@Component({
    selector: 'app-plugin-activity-list',
    imports: [
        AppTableCellDirective,
        AppTableComponent,
        DatePipe,
        LoadingSpinnerComponent,
        MatTooltip,
        PaginationControlsComponent,
    ],
    templateUrl: './plugin-activity-list.component.html',
    styleUrl: './plugin-activity-list.component.scss',
})
export class PluginActivityListComponent {
    readonly events = input.required<PluginActivityEvent[]>();
    /** For a list across organizations. */
    readonly showOrganization = input(false);
    /** For a list across plugins. */
    readonly showPlugin = input(false);
    /** Every event the filters match, on all pages. */
    readonly totalCount = input(0);
    readonly page = input(1);
    readonly pageSize = input(PLUGIN_ACTIVITY_PAGE_SIZE);
    readonly isLoading = input(false);
    /** What the list says when it has no event. */
    readonly emptyMessage = input('No activity yet.');
    readonly pageChange = output<number>();

    protected readonly columns = computed<AppTableColumnDef[]>(() => [
        WHEN_COLUMN,
        ...(this.showPlugin() ? [PLUGIN_COLUMN] : []),
        ...(this.showOrganization() ? [ORGANIZATION_COLUMN] : []),
        ACTOR_COLUMN,
        ACTION_COLUMN,
        DETAILS_COLUMN,
    ]);
    protected readonly rows = computed<TableRow[]>(() => this.events().map((event) => ({ id: event.id })));
    private readonly entriesById = computed(
        () => new Map(this.events().map((event) => [event.id, toEntry(event)] as const))
    );

    protected entryOf(row: TableRow): ActivityEntry | undefined {
        return this.entriesById().get(row['id'] as number);
    }

    protected onPageChange(page: number): void {
        this.pageChange.emit(page);
    }
}

function toEntry(event: PluginActivityEvent): ActivityEntry {
    return {
        id: event.id,
        createdAt: event.created_at,
        relativeTime: getRelativeTime(event.created_at),
        plugin: pluginActivityPluginText(event),
        organization: pluginActivityOrganizationText(event),
        actor: pluginActivityActorText(event),
        action: PLUGIN_ACTIVITY_ACTION_LABELS[event.action],
        requestLine: pluginActivityRequestLine(event),
        target: pluginActivityTargetText(event),
        detail: pluginActivityDetailText(event),
        error: pluginActivityErrorText(event),
    };
}
