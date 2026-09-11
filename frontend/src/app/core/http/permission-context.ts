import { HttpContext, HttpContextToken } from '@angular/common/http';
import { ActionCode, ResourceCode } from '@shared/models';

/** How the interceptor should evaluate the permission requirement:
 *  - `active` — check against the currently-selected org (`PermissionsService.can`).
 *  - `anyOrg` — check across every org the caller belongs to (`canInAnyOrg`); use for
 *    cross-org endpoints (workspace admin panel: orgs/users/roles/memberships lists). */
export type PermissionScope = 'active' | 'anyOrg';

/** Metadata attached to a request that the actor is only allowed to send when they hold
 *  the specified permission in the requested scope. Absent → the request is not gated. */
export interface PermissionRequirement<T = unknown> {
    resource: ResourceCode;
    action: ActionCode;
    scope: PermissionScope;
    /** Body emitted synthetically (HTTP 200) when the gate fails, so callers get a well-typed
     *  empty result instead of an error. */
    fallback: T;
}

export const PERMISSION_CTX = new HttpContextToken<PermissionRequirement | null>(() => null);

/** Tags an HTTP request with a required permission (checked against the ACTIVE org) and a
 *  fallback body used when the actor lacks that permission. `preflightPermissionInterceptor`
 *  short-circuits the request with the fallback so no 403 round-trip is made and no
 *  forbidden-loop is triggered. Use for single-org endpoints. */
export function withPermission<T>(resource: ResourceCode, action: ActionCode, fallback: T): HttpContext {
    return new HttpContext().set(PERMISSION_CTX, { resource, action, scope: 'active', fallback });
}

/** Cross-org variant of `withPermission`. The gate passes when the actor holds the permission
 *  in AT LEAST ONE org, independent of the active-org selector. Use for cross-org endpoints
 *  (workspace admin panel: orgs/users/roles/memberships lists). */
export function withCrossOrgPermission<T>(resource: ResourceCode, action: ActionCode, fallback: T): HttpContext {
    return new HttpContext().set(PERMISSION_CTX, { resource, action, scope: 'anyOrg', fallback });
}
