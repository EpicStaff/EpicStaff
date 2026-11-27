import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { TabButtonComponent } from '../../../../shared/components/tab-button/tab-button.component';
import { DASHBOARD_SESSION_STATUSES } from '../../constants/dashboard-session-statuses';
import { DashboardChartSeries, DashboardChartType } from '../../models/dashboard-chart.model';
import { DashboardPeriodUnit } from '../../models/dashboard-filters.model';
import { DashboardStats } from '../../models/dashboard-stats.model';
import { DashboardChartComponent } from '../dashboard-chart/dashboard-chart.component';

@Component({
    selector: 'app-sessions-by-status-card',
    imports: [DashboardChartComponent, TabButtonComponent, RouterLink],
    templateUrl: './sessions-by-status-card.component.html',
    styleUrls: ['./sessions-by-status-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SessionsByStatusCardComponent {
    readonly stats = input.required<DashboardStats>();
    readonly unit = input.required<DashboardPeriodUnit>();
    readonly liveNow = input.required<number>();

    protected readonly chartTypes: { type: DashboardChartType; label: string }[] = [
        { type: 'columns', label: 'Bars' },
        { type: 'lines', label: 'Lines' },
        { type: 'donut', label: 'Donut' },
    ];
    protected readonly chartType = signal<DashboardChartType>('columns');

    protected readonly labels = computed(() =>
        this.stats().periods.map(({ period }) => formatPeriod(period, this.unit()))
    );

    protected readonly series = computed<DashboardChartSeries[]>(() =>
        DASHBOARD_SESSION_STATUSES.map(({ key, label, color }) => ({
            label,
            color,
            values: this.stats().periods.map((period) => period.by_status[key]),
        }))
    );

    protected readonly legend = computed(() =>
        this.series().map((series) => ({ ...series, total: series.values.reduce((sum, value) => sum + value, 0) }))
    );

    protected readonly total = computed(() => this.legend().reduce((sum, item) => sum + item.total, 0));
}

const PERIOD_FORMATS: Record<DashboardPeriodUnit, Intl.DateTimeFormatOptions> = {
    [DashboardPeriodUnit.Day]: { month: 'short', day: 'numeric' },
    [DashboardPeriodUnit.Month]: { month: 'short', year: 'numeric' },
    [DashboardPeriodUnit.Year]: { year: 'numeric' },
};

function formatPeriod(period: string, unit: DashboardPeriodUnit): string {
    return new Date(period).toLocaleDateString('en-US', { ...PERIOD_FORMATS[unit], timeZone: 'UTC' });
}
