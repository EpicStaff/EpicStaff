import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FetchErrorStateComponent, LoadingSpinnerComponent } from 'src/app/shared/components';
import { GraphSessionStatus } from 'src/app/shared/models';

import { FirstReportStateComponent } from '../../components/first-report-state/first-report-state.component';
import { KpiCardComponent } from '../../components/kpi-card/kpi-card.component';
import { ResourceCardComponent } from '../../components/resource-card/resource-card.component';
import { UpdatedAtComponent } from '../../components/updated-at/updated-at.component';
import { DashboardReportService } from '../../services/dashboard-report.service';

@Component({
    selector: 'app-dashboard-overview-tab',
    templateUrl: './dashboard-overview-tab.component.html',
    imports: [
        ResourceCardComponent,
        KpiCardComponent,
        UpdatedAtComponent,
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

    protected readonly waitingCount = computed(
        () =>
            this.report()?.live_sessions.filter((session) => session.status === GraphSessionStatus.WAITING_FOR_USER)
                .length ?? 0
    );
}
