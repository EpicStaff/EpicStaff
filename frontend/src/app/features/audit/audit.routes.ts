import { inject } from '@angular/core';
import { CanActivateFn, Router, Routes } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { permissionGuard } from '../../core/guards/workspace.guard';
import { PermissionsService } from '../../services/auth/permissions.service';
import { allowedAuditTabs, sessionAuditEnabledGuard, userAuditEnabledGuard } from './guards/audit-domain-enabled.guard';

const AUDIT_TAB_PATHS = { sessions: 'sessions', user_actions: 'actions' } as const;

/** `/audit` → the first tab the caller may open, or the app's default route when there is none. */
export const auditIndexGuard: CanActivateFn = () => {
    const [firstTab] = allowedAuditTabs();
    return inject(Router).parseUrl(
        firstTab ? `/audit/${AUDIT_TAB_PATHS[firstTab]}` : inject(PermissionsService).resolveDefaultRoute()
    );
};

export const AUDIT_ROUTES: Routes = [
    {
        path: '',
        loadComponent: () => import('./audit-page.component').then((m) => m.AuditPageComponent),
        children: [
            { path: '', pathMatch: 'full', canActivate: [auditIndexGuard], children: [] },
            {
                path: AUDIT_TAB_PATHS.sessions,
                loadComponent: () =>
                    import('./audit-sessions-browser.component').then((m) => m.AuditSessionsBrowserComponent),
                canActivate: [sessionAuditEnabledGuard, permissionGuard],
                data: { permission: [ResourceCode.Audit, ActionCode.Read] },
            },
            {
                path: AUDIT_TAB_PATHS.user_actions,
                loadComponent: () =>
                    import('./audit-user-actions-browser.component').then((m) => m.AuditUserActionsBrowserComponent),
                canActivate: [userAuditEnabledGuard, permissionGuard],
                data: { permission: [ResourceCode.UserAudit, ActionCode.Read] },
            },
        ],
    },
];
