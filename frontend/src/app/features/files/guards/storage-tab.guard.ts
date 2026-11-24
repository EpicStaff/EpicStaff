import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';

/**
 * Permission guard for the `/storage/*` tabs. Reads [ResourceCode, ActionCode] from route.data['permission'].
 * On failure it falls back to another storage tab the caller can read instead of leaving Storage — the
 * remembered tab may no longer be permitted, and Storage should still open while any of its tabs is readable.
 */
export const storageTabGuard: CanActivateFn = (route) => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    const [resource, action] = route.data['permission'] as [ResourceCode, ActionCode];
    if (permissionsService.can(resource, action)) return true;
    return router.parseUrl(permissionsService.resolveStorageTab() ?? permissionsService.resolveDefaultRoute());
};
