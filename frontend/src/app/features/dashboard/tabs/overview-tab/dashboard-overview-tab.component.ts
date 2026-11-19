import { ChangeDetectionStrategy, Component } from '@angular/core';

import { FirstReportStateComponent } from '../../components/first-report-state/first-report-state.component';
import { KpiCardComponent } from '../../components/kpi-card/kpi-card.component';
import { ResourceCardComponent } from '../../components/resource-card/resource-card.component';
import { UpdatedAtComponent } from '../../components/updated-at/updated-at.component';

@Component({
    selector: 'app-dashboard-overview-tab',
    templateUrl: './dashboard-overview-tab.component.html',
    imports: [ResourceCardComponent, KpiCardComponent, UpdatedAtComponent, FirstReportStateComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardOverviewTabComponent {}
