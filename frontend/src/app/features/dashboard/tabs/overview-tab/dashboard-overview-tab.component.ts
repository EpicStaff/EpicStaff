import { ChangeDetectionStrategy, Component } from '@angular/core';

import { ResourceCardComponent } from '../../components/resource-card/resource-card.component';

@Component({
    selector: 'app-dashboard-overview-tab',
    templateUrl: './dashboard-overview-tab.component.html',
    imports: [ResourceCardComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardOverviewTabComponent {}
