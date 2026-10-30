import { AuditUserAction } from '../models/audit-user-action.models';

// How the recorder's own actions read in a sentence; any other action is a DRF action name from the fallback.
const ACTION_PHRASES: Record<string, string> = {
    permanently_deleted: 'permanently deleted',
    signed_in: 'signed in',
    sign_in_failed: 'sign-in failed',
    signed_out: 'signed out',
    password_reset: 'reset password',
};

function quoted(name: string): string {
    return `"${name}"`;
}

// `flow "Billing"`, `flow #4` when the record kept no name, or just `flow`
function describeObject(type: string | null, id: string | null, name: string | null): string {
    const identity = name ? quoted(name) : id ? `#${id}` : '';
    return [type, identity].filter(Boolean).join(' ');
}

// One sentence for the What column, e.g. `updated python node "Parse invoice" in flow "Billing"`.
export function describeUserAction(event: AuditUserAction): string {
    const verb = ACTION_PHRASES[event.action] ?? event.action.replaceAll('_', ' ');
    const target =
        event.action === 'renamed' && event.previous_name && event.target_name
            ? [event.target_type, `${quoted(event.previous_name)} → ${quoted(event.target_name)}`]
                  .filter(Boolean)
                  .join(' ')
            : describeObject(event.target_type, event.target_id, event.target_name);
    const parent = describeObject(event.parent_type, event.parent_id, event.parent_name);
    return [verb, target, parent && `in ${parent}`].filter(Boolean).join(' ');
}
