import { AuditUserAction } from '../models/audit-user-action.models';
import { USER_ACTION_OPTIONS } from '../models/audit-user-action-filter-options';

const ACTION_LABELS = new Map(USER_ACTION_OPTIONS.map((option) => [option.value, option.label]));

function quoted(name: string): string {
    return `"${name}"`;
}

// `flow "Billing"`, `flow #4` when the record kept no name, or just `flow`
function describeObject(type: string | null, id: string | null, name: string | null): string {
    const identity = name ? quoted(name) : id ? `#${id}` : '';
    return [type, identity].filter(Boolean).join(' ');
}

// The filter's label for a known action; any other action is a backend action name, e.g. `import_entity` → "Import entity".
export function userActionLabel(action: string): string {
    const humanized = action.replaceAll('_', ' ');
    return ACTION_LABELS.get(action) ?? humanized.charAt(0).toUpperCase() + humanized.slice(1);
}

// `python node "Parse invoice"`, or `flow "Old" → "New"` for a rename; empty when the action has no target
export function userActionTarget(event: AuditUserAction): string {
    if (event.action === 'renamed' && event.previous_name && event.target_name) {
        return [event.target_type, `${quoted(event.previous_name)} → ${quoted(event.target_name)}`]
            .filter(Boolean)
            .join(' ');
    }
    return describeObject(event.target_type, event.target_id, event.target_name);
}

// `in flow "Billing"`, or empty when the record has no parent
export function userActionParent(event: AuditUserAction): string {
    const parent = describeObject(event.parent_type, event.parent_id, event.parent_name);
    return parent && `in ${parent}`;
}
