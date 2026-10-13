import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { of } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { PERMISSION_CTX } from '../http/permission-context';

/** Short-circuits any HTTP request tagged with `withPermission(...)` / `withCrossOrgPermission(...)`
 *  when the permission set for the tag's scope is loaded and does not grant that permission.
 *  Returns HTTP 200 with the caller-provided fallback body instead of hitting the network — this
 *  prevents the `forbiddenInterceptor` from entering its refetch→remount→403 loop for
 *  known-forbidden calls.
 *
 *  If that permission set is not loaded (never fetched, or cleared, e.g. mid org-switch), the
 *  answer is unknown rather than "denied", so the request goes to the server. A real 403 then lets
 *  `forbiddenInterceptor` refresh the permissions; faking an empty 200 would show "nothing here"
 *  and leave the stale cache in place. Untagged requests pass through unchanged. */
export const preflightPermissionInterceptor: HttpInterceptorFn = (req, next) => {
    const tag = req.context.get(PERMISSION_CTX);
    if (tag === null) {
        return next(req);
    }

    const permissions = inject(PermissionsService);
    const isCrossOrg = tag.scope === 'anyOrg';
    const isLoaded = isCrossOrg ? permissions.isOrgPermissionsLoaded() : permissions.isActivePermissionsLoaded();
    const allowed = isCrossOrg
        ? permissions.canInAnyOrg(tag.resource, tag.action)
        : permissions.can(tag.resource, tag.action);
    if (allowed || !isLoaded) {
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
