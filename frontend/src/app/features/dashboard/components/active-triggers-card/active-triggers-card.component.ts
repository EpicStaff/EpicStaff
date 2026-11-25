import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { getRelativeTime } from '@shared/utils';

import { DASHBOARD_TRIGGER_TYPES } from '../../constants/dashboard-trigger-types';
import {
    DashboardActiveTrigger,
    DashboardLiveSession,
    DashboardTriggerType,
} from '../../models/dashboard-report.model';
import {
    ActiveTriggersDialogComponent,
    ActiveTriggersDialogData,
} from '../active-triggers-dialog/active-triggers-dialog.component';

const PREVIEW_ROWS = 7;

@Component({
    selector: 'app-active-triggers-card',
    imports: [DatePipe],
    templateUrl: './active-triggers-card.component.html',
    styleUrls: ['./active-triggers-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActiveTriggersCardComponent {
    readonly triggers = input.required<DashboardActiveTrigger[]>();
    readonly waitingSessions = input.required<DashboardLiveSession[]>();
    private readonly dialog = inject(Dialog);
    protected readonly previewRows = PREVIEW_ROWS;
    protected readonly total = computed(() => this.triggers().length + this.waitingSessions().length);

    protected readonly triggerTypes = DASHBOARD_TRIGGER_TYPES;
    protected readonly getRelativeTime = getRelativeTime;

    protected readonly previewWaitingSessions = computed(() => this.waitingSessions().slice(0, PREVIEW_ROWS));
    protected readonly previewTriggers = computed(() =>
        this.triggers().slice(0, PREVIEW_ROWS - this.previewWaitingSessions().length)
    );

    protected readonly summary = computed(() =>
        Object.values(DashboardTriggerType)
            .map((type) => {
                const count = this.triggers().filter((trigger) => trigger.trigger_type === type).length;
                return `${DASHBOARD_TRIGGER_TYPES[type].label} ${count}`;
            })
            .join(' · ')
    );

    protected openAll(): void {
        this.dialog.open<void, ActiveTriggersDialogData>(ActiveTriggersDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            maxWidth: '100vw',
            data: { triggers: this.triggers(), waitingSessions: this.waitingSessions() },
        });
    }
}
