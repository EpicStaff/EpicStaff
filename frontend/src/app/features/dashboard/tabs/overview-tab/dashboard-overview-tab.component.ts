import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FetchErrorStateComponent, LoadingSpinnerComponent } from '@shared/components';
import { GraphSessionStatus } from '@shared/models';

import { ActiveTriggersCardComponent } from '../../components/active-triggers-card/active-triggers-card.component';
import { FirstReportStateComponent } from '../../components/first-report-state/first-report-state.component';
import { KpiCardComponent } from '../../components/kpi-card/kpi-card.component';
import { DashboardReportService } from '../../services/dashboard-report.service';

@Component({
    selector: 'app-dashboard-overview-tab',
    templateUrl: './dashboard-overview-tab.component.html',
    styleUrls: ['./dashboard-overview-tab.component.scss'],
    imports: [
        ActiveTriggersCardComponent,
        KpiCardComponent,
        FirstReportStateComponent,
        FetchErrorStateComponent,
        LoadingSpinnerComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardOverviewTabComponent {
    private readonly reportService = inject(DashboardReportService);

    protected readonly resource = this.reportService.resource;
    protected readonly report = this.reportService.report;

    protected readonly waitingSessions = computed(() =>
        (this.report()?.live_sessions ?? []).filter((session) => session.status === GraphSessionStatus.WAITING_FOR_USER)
    );
}
