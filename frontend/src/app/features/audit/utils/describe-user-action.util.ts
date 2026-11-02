import { AuditUserAction } from '../models/audit-user-action.models';
import { USER_ACTION_OPTIONS } from '../models/audit-user-action-filter-options';

const ACTION_LABELS = new Map(USER_ACTION_OPTIONS.map((option) => [option.value, option.label]));

function quoted(name: string): string {
    return `"${name}"`;
}

// `"Billing"`, `#4` when the record kept no name, or empty
function nameOrId(name: string | null, id: string | null): string {
    return name ? quoted(name) : id ? `#${id}` : '';
}

// The filter's label for a known action; any other action is a backend action name, e.g. `import_entity` → "Import entity".
export function userActionLabel(action: string): string {
    const humanized = action.replaceAll('_', ' ');
    return ACTION_LABELS.get(action) ?? humanized.charAt(0).toUpperCase() + humanized.slice(1);
}

// `"Parse invoice"`, `"Old" → "New"` for a rename, `#12`, or empty when the action has no target
export function userActionTargetName(event: AuditUserAction): string {
    if (event.action === 'renamed' && event.previous_name && event.target_name) {
        return `${quoted(event.previous_name)} → ${quoted(event.target_name)}`;
    }
    return nameOrId(event.target_name, event.target_id);
}

// `flow "Billing"`, `agent "Researcher"`, `flow #12` when the record kept no name, or empty when it has no parent
export function userActionParent(event: AuditUserAction): string {
    return [event.parent_type, nameOrId(event.parent_name, event.parent_id)].filter(Boolean).join(' ');
}
