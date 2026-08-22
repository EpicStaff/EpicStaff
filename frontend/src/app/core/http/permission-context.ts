import { HttpContext, HttpContextToken } from '@angular/common/http';
import { ActionCode, ResourceCode } from '@shared/models';

/** Metadata attached to a request that the actor is only allowed to send when they hold
 *  the specified permission in their active org. Absent → the request is not gated. */
export interface PermissionRequirement<T = unknown> {
    resource: ResourceCode;
    action: ActionCode;
    /** Body emitted synthetically (HTTP 200) when the gate fails, so callers get a well-typed
     *  empty result instead of an error. */
    fallback: T;
}

export const PERMISSION_CTX = new HttpContextToken<PermissionRequirement | null>(() => null);

/** Tags an HTTP request with a required permission and a fallback body used when the actor
 *  lacks that permission. `preflightPermissionInterceptor` short-circuits the request with
 *  the fallback so no 403 round-trip is made and no forbidden-loop is triggered. */
export function withPermission<T>(resource: ResourceCode, action: ActionCode, fallback: T): HttpContext {
    return new HttpContext().set(PERMISSION_CTX, { resource, action, fallback });
}
