import { HttpContext, HttpErrorResponse } from '@angular/common/http';

import { SKIP_FORBIDDEN_RELOAD } from './skip-forbidden-reload.context';

/**
 * Error codes for a 403 that reflects a fixed business rule on the targeted row (e.g.
 * "this specific row can't be edited"), not a change in the caller's own permissions.
 * These must not trigger forbiddenInterceptor's toast and session refresh/reload — the caller's own error
 * handling shows the message instead.
 */
const BUSINESS_RULE_FORBIDDEN_CODES = new Set<string>([
    'built_in_model_immutable',
    'permission_escalation_denied',
    'in_use_restricted',
    // A flow save with a Key-Value node whose mode needs a key_value_tables permission the role lacks
    // (read: R, write: C and U, delete: D); the save's own error handling shows it.
    'key_value_mode_denied',
    // An upload over an existing file without FILES:UPDATE; the upload's own error handling shows it.
    'overwrite_not_permitted',
    // A copy, import, partial import or version restore / new flow from a version of a flow with trigger nodes,
    // without Flows:Use; UsePermissionRefusalService shows it.
    'flow_with_trigger_nodes_requires_use_permission',
    // An edit of a flow node (single save or flow bulk save) or of a virtualenv its code runs in, needing a files
    // permission the user lacks; the flow save handler or the venv dialog shows the message, and the session is
    // deliberately not refreshed, since the user's role did not change.
    'storage_grant_denied',
    // A copy, version restore or new flow from a version holding code that reads secrets, without Secrets:Use;
    // UsePermissionRefusalService shows it (tool copy shows it in its own error banner or toast).
    'code_with_secrets_requires_secrets_use_permission',
]);

/**
 * True when forbiddenInterceptor has already told the user about this error (an error toast with the
 * server's message, then a permission refresh). The caller's own error handling must then stay quiet,
 * or the user sees the same 403 twice. Pass the request's context when it was sent with one.
 */
export function wasHandledByForbiddenInterceptor(
    error: unknown,
    requestContext: HttpContext = new HttpContext()
): boolean {
    return (
        error instanceof HttpErrorResponse &&
        error.status === 403 &&
        !requestContext.get(SKIP_FORBIDDEN_RELOAD) &&
        !BUSINESS_RULE_FORBIDDEN_CODES.has(error.error?.code)
    );
}
