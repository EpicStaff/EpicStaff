import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { formatDate } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    TableRow,
} from '@shared/components';
import { getRelativeTime } from '@shared/utils';

import { DASHBOARD_TRIGGER_TYPES } from '../../constants/dashboard-trigger-types';
import { DashboardActiveTrigger, DashboardLiveSession } from '../../models/dashboard-report.model';

export interface ActiveTriggersDialogData {
    triggers: DashboardActiveTrigger[];
    waitingSessions: DashboardLiveSession[];
}

const WAITING = 'waiting';

@Component({
    selector: 'app-active-triggers-dialog',
    imports: [AppTableComponent, AppTableCellDirective, AppSvgIconComponent, MatTooltip],
    templateUrl: './active-triggers-dialog.component.html',
    styleUrls: ['./active-triggers-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActiveTriggersDialogComponent {
    private readonly dialogRef = inject(DialogRef);
    private readonly data = inject<ActiveTriggersDialogData>(DIALOG_DATA);

    protected readonly rows: TableRow[] = [
        ...this.data.waitingSessions.map((session) => ({
            id: `session-${session.session_id}`,
            type: WAITING,
            icon: 'ti-hourglass',
            label: `Session #${session.session_id}`,
            flow: session.graph_name,
            when: `Started ${getRelativeTime(session.created_at)}`,
            status: 'Waiting for user',
        })),
        ...this.data.triggers.map((trigger) => {
            const type = DASHBOARD_TRIGGER_TYPES[trigger.trigger_type];
            return {
                id: `${trigger.trigger_type}-${trigger.node_id}`,
                type: trigger.trigger_type,
                icon: type.icon,
                label: type.label,
                flow: trigger.graph_name,
                when: trigger.next_run_at
                    ? formatDate(trigger.next_run_at, 'MMM d, HH:mm', 'en-US')
                    : getRelativeTime(trigger.last_event_at),
                status: type.status,
            };
        }),
    ];

    protected readonly columns: AppTableColumnDef[] = [
        { key: 'type', label: 'Trigger', width: 'minmax(180px, 1fr)', filterItems: TYPE_FILTER_ITEMS },
        { key: 'flow', label: 'Flow', width: 'minmax(220px, 2fr)', filterItems: toFilterItems(this.rows, 'flow') },
        { key: 'when', label: 'Next run / last event', width: 'minmax(180px, 1fr)' },
        {
            key: 'status',
            label: 'Status',
            width: 'minmax(160px, 1fr)',
            filterItems: toFilterItems(this.rows, 'status'),
        },
    ];

    protected close(): void {
        this.dialogRef.close();
    }
}

const TYPE_FILTER_ITEMS = [
    ...Object.entries(DASHBOARD_TRIGGER_TYPES).map(([value, type]) => ({ name: type.label, value })),
    { name: 'Waiting session', value: WAITING },
];

function toFilterItems(rows: TableRow[], key: string): { name: string; value: string }[] {
    return [...new Set(rows.map((row) => String(row[key])))].sort().map((value) => ({ name: value, value }));
}
