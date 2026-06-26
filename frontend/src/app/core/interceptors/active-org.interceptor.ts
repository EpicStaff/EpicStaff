import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { ActiveOrgService } from '../../services/auth/active-org.service';

export const activeOrgInterceptor: HttpInterceptorFn = (req, next) => {
    const activeOrg = inject(ActiveOrgService);
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
