import { SelectItem, TableRow } from '@shared/components';
import { GetRoleResponse } from '@shared/models';

/** Pure helpers shared by the selectable "row + role" tables (organization members, user's organizations). */

export function roleToSelectItem(role: GetRoleResponse): SelectItem<number> {
    return { name: role.name, value: role.id };
}

/** Returns `rows` with `role` set to `roleId` on the rows whose `id` is in `rowIds`. */
export function withRole(rows: TableRow[], rowIds: Set<number>, roleId: number): TableRow[] {
    return rows.map((row) => (rowIds.has(row['id'] as number) ? { ...row, role: roleId } : row));
}

/** Rows of `selection` that were not selected before and have no role yet. */
export function newRoleLessRows(selection: TableRow[], previouslySelectedIds: Set<number>): TableRow[] {
    return selection.filter((row) => !previouslySelectedIds.has(row['id'] as number) && row['role'] == null);
}

/** Order-insensitive id comparison, used as a `computed` equality so an unchanged id set keeps its reference. */
export function haveSameIds(first: number[], second: number[]): boolean {
    if (first.length !== second.length) return false;
    const secondIds = new Set(second);
    return first.every((id) => secondIds.has(id));
}
