import { ActionCode, CatalogResourceType, CatalogResponse } from '@shared/models';
import { RolePermissionExtension, RolePermissionExtensionRow } from '@shared/services';

import { GROUP_META, GroupMeta } from '../../constants/permission-table.constant';
import { PermissionMatrixGroup, PermissionMatrixRow } from './permission-matrix.model';

/** The selection key of one cell. */
export function permissionKey(code: string, action: ActionCode): string {
    return `${code}:${action}`;
}

/** Every cell key of the rows. */
export function matrixRowKeys(rows: readonly PermissionMatrixRow[]): string[] {
    return rows.flatMap((row) => row.actions.map((action) => permissionKey(row.code, action)));
}

/** The catalog's resource types as matrix groups, in catalog order, labelled by `GROUP_META`. */
export function catalogMatrixGroups(catalog: CatalogResponse): PermissionMatrixGroup[] {
    const rowsByGroup = new Map<string, PermissionMatrixRow[]>();
    for (const resourceType of catalog.resource_types) {
        const rows = rowsByGroup.get(resourceType.group) ?? [];
        rows.push(catalogMatrixRow(resourceType));
        rowsByGroup.set(resourceType.group, rows);
    }
    return Array.from(rowsByGroup, ([key, rows]) => {
        const meta: GroupMeta = GROUP_META[key] ?? { label: key, icon: 'settings' };
        return { key, label: meta.label, icon: meta.icon, iconClass: null, rows };
    });
}

/** An extension's rows as one matrix group. */
export function extensionMatrixGroup(
    extension: RolePermissionExtension,
    rows: readonly RolePermissionExtensionRow[]
): PermissionMatrixGroup {
    return {
        key: extension.groupKey,
        label: extension.groupLabel,
        icon: null,
        iconClass: extension.groupIconClass,
        rows: rows.map((row) => extensionMatrixRow(row)),
    };
}

function catalogMatrixRow(resourceType: CatalogResourceType): PermissionMatrixRow {
    const recommendedWith: Partial<Record<ActionCode, string[]>> = {};
    for (const action of Object.values(ActionCode)) {
        const cells = resourceType.recommended_with[action] ?? [];
        if (cells.length > 0) {
            recommendedWith[action] = cells.map((cell) => permissionKey(cell.resource_type, cell.action));
        }
    }
    return {
        code: resourceType.code,
        label: resourceType.label,
        description: resourceType.description,
        iconUrl: null,
        actions: resourceType.applicable_actions,
        actionDescriptions: {},
        recommendedWith,
    };
}

/** `requires` is enforced when cells are ticked (see `PermissionExtensionRowsService`), so it is no recommendation. */
function extensionMatrixRow(row: RolePermissionExtensionRow): PermissionMatrixRow {
    const actionDescriptions: Partial<Record<ActionCode, string>> = {};
    for (const cell of row.actions) actionDescriptions[cell.action] = cell.description;
    return {
        code: row.code,
        label: row.label,
        description: row.description,
        iconUrl: row.iconUrl,
        actions: row.actions.map((cell) => cell.action),
        actionDescriptions,
        recommendedWith: {},
    };
}
