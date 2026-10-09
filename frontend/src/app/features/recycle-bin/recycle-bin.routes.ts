import { inject } from '@angular/core';
import { CanActivateFn, Router, Routes } from '@angular/router';
import { ActionCode } from '@shared/models';

import { permissionGuard } from '../../core/guards/workspace.guard';
import { PermissionsService } from '../../services/auth/permissions.service';
import { RecycleBinTabComponent } from './components/recycle-bin-tab/recycle-bin-tab.component';
import { RECYCLE_BIN_TABS } from './constants/recycle-bin-tabs.constants';
import { RecycleBinPageComponent } from './pages/recycle-bin-page/recycle-bin-page.component';
import { visibleRecycleBinTabs } from './utils/visible-recycle-bin-tabs.util';

/** `/recycle-bin` → the first tab the user may read, or the app's default route when there is none. */
export const recycleBinIndexGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    const [firstTab] = visibleRecycleBinTabs((resource, action) => permissionsService.can(resource, action));
    return inject(Router).parseUrl(
        firstTab ? `/recycle-bin/${firstTab.key}` : permissionsService.resolveDefaultRoute()
    );
};

export const RECYCLE_BIN_ROUTES: Routes = [
    {
        path: '',
        component: RecycleBinPageComponent,
        children: [
            { path: '', pathMatch: 'full', canActivate: [recycleBinIndexGuard], children: [] },
            ...RECYCLE_BIN_TABS.map((tab) => ({
                path: tab.key,
                component: RecycleBinTabComponent,
                canActivate: [permissionGuard],
                data: { permission: [tab.resource, ActionCode.Read], recycleBinTab: tab.key },
            })),
        ],
    },
];
