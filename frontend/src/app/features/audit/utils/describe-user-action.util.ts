import { AuditUserAction } from '../models/audit-user-action.models';
import { USER_ACTION_OPTIONS } from '../models/audit-user-action-filter-options';

const ACTION_LABELS = new Map(USER_ACTION_OPTIONS.map((option) => [option.value, option.label]));

// `Billing`, `#4` when the record kept no name, or empty
function nameOrId(name: string | null, id: string | null): string {
    return name || (id ? `#${id}` : '');
}

function capitalized(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}

// The filter's label for a known action; any other action is a backend action name, e.g. `import_entity` → "Import entity".
export function userActionLabel(action: string): string {
    return ACTION_LABELS.get(action) ?? capitalized(action.replaceAll('_', ' '));
}

// A recorded type as a reader sees it, `python node` → "Python node"; the filters still match the raw value.
export function userActionTypeLabel(type: string | null): string {
    return type ? capitalized(type) : '';
}

// `Parse invoice`, `Old → New` for a rename, `#12`, or empty when the action has no target
export function userActionTargetName(event: AuditUserAction): string {
    if (event.action === 'renamed' && event.previous_name && event.target_name) {
        return `${event.previous_name} → ${event.target_name}`;
    }
    return nameOrId(event.target_name, event.target_id);
}

// `Billing`, `#12` when the record kept no name, or empty when it has no parent; the parent's type is shown apart
export function userActionParentName(event: AuditUserAction): string {
    return nameOrId(event.parent_name, event.parent_id);
}
