import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { of } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { PERMISSION_CTX } from '../http/permission-context';

/** Short-circuits any HTTP request tagged with `withPermission(...)` / `withCrossOrgPermission(...)`
 *  when the current actor lacks that permission in the tag's scope. Returns HTTP 200 with the
 *  caller-provided fallback body instead of hitting the network — this prevents the
 *  `forbiddenInterceptor` from entering its refetch→remount→403 loop for known-forbidden
 *  calls. Untagged requests pass through unchanged. */
export const preflightPermissionInterceptor: HttpInterceptorFn = (req, next) => {
    const tag = req.context.get(PERMISSION_CTX);
    if (tag === null) {
        return next(req);
    }

    const permissions = inject(PermissionsService);
    const allowed =
        tag.scope === 'anyOrg'
            ? permissions.canInAnyOrg(tag.resource, tag.action)
            : permissions.can(tag.resource, tag.action);
    if (allowed) {
        return next(req);
    }

    return of(
        new HttpResponse({
            status: 200,
            url: req.urlWithParams,
            body: tag.fallback,
        })
    );
};
