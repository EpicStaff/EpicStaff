import { RolePermission } from '@shared/models';

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
