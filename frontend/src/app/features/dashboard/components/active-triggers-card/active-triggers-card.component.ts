import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { getRelativeTime } from '@shared/utils';

import {
    DashboardActiveTrigger,
    DashboardLiveSession,
    DashboardTriggerType,
} from '../../models/dashboard-report.model';

const TRIGGER_TYPES: Record<DashboardTriggerType, { icon: string; label: string; note: string }> = {
    [DashboardTriggerType.Schedule]: { icon: 'ti-calendar-event', label: 'Schedule', note: 'Not scheduled' },
    [DashboardTriggerType.Webhook]: { icon: 'ti-world', label: 'Webhook', note: 'On request' },
    [DashboardTriggerType.Telegram]: { icon: 'ti-brand-telegram', label: 'Telegram', note: 'On message' },
};

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

    protected readonly triggerTypes = TRIGGER_TYPES;
    protected readonly getRelativeTime = getRelativeTime;

    protected readonly summary = computed(() =>
        Object.values(DashboardTriggerType)
            .map((type) => {
                const count = this.triggers().filter((trigger) => trigger.trigger_type === type).length;
                return `${TRIGGER_TYPES[type].label} ${count}`;
            })
            .join(' · ')
    );
}
