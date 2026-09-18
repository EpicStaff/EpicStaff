import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';

/**
 * Parent guard for /workspace. Permissions are already loaded by bootstrapGuard
 * (parent canActivate on MainLayoutComponent), so this just checks access.
 */
export const workspaceGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    return permissionsService.canAccessWorkspace() ? true : router.parseUrl(permissionsService.resolveDefaultRoute());
};

/** /workspace index redirect — sends the caller to their first accessible workspace tab. */
export const workspaceIndexGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    return router.parseUrl(permissionsService.resolveDefaultWorkspaceTab() ?? permissionsService.resolveDefaultRoute());
};

/**
 * Cross-org permission guard for /workspace/* tabs. Reads [ResourceCode, ActionCode]
 * from route.data['permission'] and checks `canInAnyOrg` (any org the caller belongs to),
 * not the currently-active org. On failure, redirects to the first accessible workspace tab.
 */
export const workspacePermissionGuard: CanActivateFn = (route) => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    const [resource, action] = route.data['permission'] as [ResourceCode, ActionCode];
    if (permissionsService.canInAnyOrg(resource, action)) return true;
    return router.parseUrl(permissionsService.resolveDefaultWorkspaceTab() ?? permissionsService.resolveDefaultRoute());
};

/** /workspace/main — superadmins only. Non-SA bounce to the first accessible workspace tab. */
export const superAdminGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    if (permissionsService.isSuperadmin) return true;
    const tab = permissionsService.resolveDefaultWorkspaceTab();
    return router.parseUrl(tab ?? permissionsService.resolveDefaultRoute());
};

/**
 * Generic permission guard. Reads [ResourceCode, ActionCode] from route.data['permission'].
 * Redirects to the first accessible route on failure.
 */
export const permissionGuard: CanActivateFn = (route) => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    const [resource, action] = route.data['permission'] as [ResourceCode, ActionCode];
    return permissionsService.can(resource, action) ? true : router.parseUrl(permissionsService.resolveDefaultRoute());
};
