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
    /** Body emitted synthetically (HTTP 200) when the permission set for `scope` is loaded and does
     *  not grant the permission, so callers get a well-typed empty result instead of an error.
     *  While that set is not loaded the request goes to the network instead. */
    fallback: T;
}

export const PERMISSION_CTX = new HttpContextToken<PermissionRequirement | null>(() => null);

/** Tags an HTTP request with a required permission (checked against the ACTIVE org) and a
 *  fallback body. When the active-org permissions are loaded and lack that permission,
 *  `preflightPermissionInterceptor` short-circuits the request with the fallback so no 403
 *  round-trip is made and no forbidden-loop is triggered; while they are not loaded the request
 *  is sent. Use for single-org endpoints. */
export function withPermission<T>(resource: ResourceCode, action: ActionCode, fallback: T): HttpContext {
    return new HttpContext().set(PERMISSION_CTX, { resource, action, scope: 'active', fallback });
}

/** Cross-org variant of `withPermission`. The gate passes when the actor holds the permission
 *  in AT LEAST ONE org, independent of the active-org selector; the fallback is used only once the
 *  cross-org capabilities (`/me/orgs/`) are loaded. Use for cross-org endpoints
 *  (workspace admin panel: orgs/users/roles/memberships lists). */
export function withCrossOrgPermission<T>(resource: ResourceCode, action: ActionCode, fallback: T): HttpContext {
    return new HttpContext().set(PERMISSION_CTX, { resource, action, scope: 'anyOrg', fallback });
}
