import { ActionCode, RolePermission } from '@shared/models';

/** Converts a role's permissions array to a flat Set of "resource_type:action" strings
 *  used for O(1) lookup in the permissions table. */
export function rolePermissionsToSet(permissions: RolePermission[]): Set<string> {
    const set = new Set<string>();
    for (const p of permissions) {
        for (const a of p.actions) {
            set.add(`${p.resource_type}:${a}`);
        }
    }
    return set;
}

/** Inverse of {@link rolePermissionsToSet}: converts a flat Set of "resource:action" keys
 *  back into a `RolePermission[]` grouped by resource. Resources with no actions are
 *  omitted (matching the backend contract). */
export function setToRolePermissions(keys: Set<string>): RolePermission[] {
    const grouped = new Map<string, ActionCode[]>();
    for (const key of keys) {
        const idx = key.indexOf(':');
        if (idx === -1) continue;
        const resource = key.slice(0, idx);
        const action = key.slice(idx + 1) as ActionCode;
        const actions = grouped.get(resource) ?? [];
        actions.push(action);
        grouped.set(resource, actions);
    }
    return Array.from(grouped.entries()).map(([resource_type, actions]) => ({
        resource_type,
        actions,
    }));
}
