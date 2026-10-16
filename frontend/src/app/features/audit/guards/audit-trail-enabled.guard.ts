import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';

/**
 * Blocks the audit page when the deployment runs without the audit trail (the auditor
 * service is not started then, so the page could only show errors). Redirects to the
 * caller's default route, the same way a forbidden page does.
 */
export const auditTrailEnabledGuard: CanActivateFn = () => {
    const configService = inject(ConfigService);
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    return configService.isAuditTrailEnabled ? true : router.parseUrl(permissionsService.resolveDefaultRoute());
};
