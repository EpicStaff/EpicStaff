import { Routes } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { permissionGuard } from '../../core/guards/workspace.guard';
import { DashboardTab } from './constants/dashboard-tabs';

export const DASHBOARD_ROUTES: Routes = [
    {
        path: '',
        loadComponent: () => import('./dashboard-page.component').then((m) => m.DashboardPageComponent),
        canActivate: [permissionGuard],
        data: { permission: [ResourceCode.Dashboard, ActionCode.Read] },
        children: [
            { path: '', redirectTo: DashboardTab.Overview, pathMatch: 'full' },
            {
                path: DashboardTab.Overview,
                loadComponent: () =>
                    import('./tabs/overview-tab/dashboard-overview-tab.component').then(
                        (m) => m.DashboardOverviewTabComponent
                    ),
            },
        ],
    },
];
