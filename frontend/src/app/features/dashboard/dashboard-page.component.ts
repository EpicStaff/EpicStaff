import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { RouteTab, RouteTabsComponent } from '@shared/components';

import { DashboardTab } from './constants/dashboard-tabs';

@Component({
    selector: 'app-dashboard-page',
    imports: [RouterOutlet, RouteTabsComponent],
    templateUrl: './dashboard-page.component.html',
    styleUrls: ['./dashboard-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardPageComponent {
    protected readonly tabs: RouteTab[] = [
        { routerLink: DashboardTab.Overview, label: 'Overview', isPermitted: () => true },
    ];
}
