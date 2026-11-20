import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { RouteTab, RouteTabsComponent } from '@shared/components';

import { DashboardToolbarComponent } from './components/dashboard-toolbar/dashboard-toolbar.component';
import { UpdatedAtComponent } from './components/updated-at/updated-at.component';
import { DashboardTab } from './constants/dashboard-tabs';
import { DashboardFiltersService } from './services/dashboard-filters.service';
import { DashboardReportService } from './services/dashboard-report.service';

@Component({
    selector: 'app-dashboard-page',
    imports: [RouterOutlet, RouteTabsComponent, DashboardToolbarComponent, UpdatedAtComponent],
    providers: [DashboardFiltersService, DashboardReportService],
    templateUrl: './dashboard-page.component.html',
    styleUrls: ['./dashboard-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardPageComponent {
    protected readonly report = inject(DashboardReportService).report;
    protected readonly tabs: RouteTab[] = [
        { routerLink: DashboardTab.Overview, label: 'Overview', isPermitted: () => true },
    ];
}
