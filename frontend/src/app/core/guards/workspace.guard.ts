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

    const hasAccess =
        permissionsService.isSuperadmin ||
        permissionsService.can('organizations', 'read') ||
        permissionsService.can('users', 'read') ||
        permissionsService.can('roles', 'read');
    return hasAccess ? true : router.parseUrl('/projects/my');
};

/** /workspace/main — superadmins only. */
export const superAdminGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    return permissionsService.isSuperadmin ? true : router.parseUrl('/workspace/users');
};

/**
 * Generic permission guard. Reads [ResourceCode, ActionCode] from route.data['permission'].
 * Redirects to /workspace/users on failure.
 */
export const permissionGuard: CanActivateFn = (route) => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    const [resource, action] = route.data['permission'] as [ResourceCode, ActionCode];
    return permissionsService.can(resource, action) ? true : router.parseUrl('/workspace/users');
};
