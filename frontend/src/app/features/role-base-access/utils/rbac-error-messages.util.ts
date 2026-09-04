import { HttpErrorResponse } from '@angular/common/http';

/** Maps backend `code` values to user-facing messages.
 *  Callers can fall back to `err.error?.message` or a generic string for unknown codes. */
const CODE_TO_MESSAGE: Record<string, string> = {
    permission_denied: 'You do not have permission to perform this action.',
    cannot_modify_self_membership: 'You can\u2019t modify your own membership.',
    membership_already_exists: 'Already a member of this organization.',
    user_not_found: 'No account with that email \u2014 ask a superadmin to create the account first.',
    invalid_role_assignment: 'That role can\u2019t be assigned here.',
    membership_not_found: 'Membership not found.',
    organization_not_found: 'Organization not found.',
    organization_name_conflict: 'An organization with that name already exists.',
    last_superadmin: 'At least one active superadmin must remain.',
    superadmin_not_assignable: 'Superadmins already have access to every organization and cannot be added as members.',
    user_not_active: 'This account is deactivated and cannot be added to an organization.',
};

/** Best-effort resolver: prefer the mapped message for a known `code`,
 *  then `error.message`, then a caller-supplied fallback. */
export function rbacErrorMessage(err: unknown, fallback = 'Operation failed'): string {
    if (err instanceof HttpErrorResponse) {
        const code = err.error?.code as string | undefined;
        if (code && CODE_TO_MESSAGE[code]) return CODE_TO_MESSAGE[code];
        const message = err.error?.message as string | undefined;
        if (message) return message;
    }
    return fallback;
}
