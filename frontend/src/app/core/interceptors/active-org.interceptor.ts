import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ORG_ID_OVERRIDE } from './org-id-override.context';

export const activeOrgInterceptor: HttpInterceptorFn = (req, next) => {
    const activeOrg = inject(ActiveOrgService);
    const permissions = inject(PermissionsService);

    const override = req.context.get(ORG_ID_OVERRIDE);

    // Token is explicitly set AND caller is a superadmin → apply the org override.
    // Non-superadmins cannot use this token even if somehow set (safety check).
    if (override !== undefined && permissions.isSuperadmin) {
        if (override !== null) {
            req = req.clone({
                setHeaders: { 'X-Organization-Id': String(override) },
            });
        }
        // override === null → omit the header so the backend returns all-org data.
        return next(req);
    }

    // Default behaviour: inject the active org header when present.
    const orgId = activeOrg.activeOrgId();
    if (orgId && !shouldSkip(req.url)) {
        req = req.clone({
            setHeaders: { 'X-Organization-Id': String(orgId) },
        });
    }

    return next(req);
};

function shouldSkip(url: string): boolean {
    return url.includes('/api/auth/') || /\/admin\/organizations\/\d+\//.test(url);
}
