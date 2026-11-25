import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { getRelativeTime } from '@shared/utils';

import { DASHBOARD_TRIGGER_TYPES } from '../../constants/dashboard-trigger-types';
import {
    DashboardActiveTrigger,
    DashboardLiveSession,
    DashboardTriggerType,
} from '../../models/dashboard-report.model';

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
}
