import { ActionCode, CatalogAction, CatalogResourceType, CatalogResponse, ResourceCode } from '@shared/models';

import { GROUP_META, GroupMeta } from '../constants/permission-table.constant';

export interface CatalogGroup {
    key: string;
    label: string;
    icon: string;
    resources: CatalogResourceType[];
}

/** What a role grants: `'*'` for a superadmin (everything applicable), otherwise actions per resource. */
export type RoleGrants = '*' | Partial<Record<ResourceCode, readonly ActionCode[]>>;

export interface GrantedResource {
    resource: CatalogResourceType;
    grantedActions: ReadonlySet<ActionCode>;
}

export interface GrantedPermissionGroup {
    key: string;
    label: string;
    /** Catalog actions granted on at least one resource of the group, in catalog order. */
    actions: CatalogAction[];
    resources: GrantedResource[];
    permissionCount: number;
}

/** Groups catalog resources by their `group`, in catalog order, with label and icon from `GROUP_META`. */
export function groupCatalogResources(catalog: CatalogResponse): CatalogGroup[] {
    const groupMap = new Map<string, CatalogResourceType[]>();
    for (const resourceType of catalog.resource_types) {
        const resources = groupMap.get(resourceType.group) ?? [];
        resources.push(resourceType);
        groupMap.set(resourceType.group, resources);
    }
    return Array.from(groupMap.entries()).map(([key, resources]) => {
        const meta: GroupMeta = GROUP_META[key] ?? { label: key, icon: 'settings' };
        return { key, label: meta.label, icon: meta.icon, resources };
    });
}

/**
 * Catalog groups reduced to what the role grants: resources without a granted applicable action,
 * groups without such resources, and action columns nobody in the group has are all dropped.
 */
export function buildGrantedPermissionGroups(catalog: CatalogResponse, grants: RoleGrants): GrantedPermissionGroup[] {
    return groupCatalogResources(catalog)
        .map((group) => {
            const resources = group.resources
                .map((resource) => ({ resource, grantedActions: grantedActionsFor(resource, grants) }))
                .filter((entry) => entry.grantedActions.size > 0);
            const actions = catalog.actions.filter((action) =>
                resources.some((entry) => entry.grantedActions.has(action.code))
            );
            const permissionCount = resources.reduce((total, entry) => total + entry.grantedActions.size, 0);
            return { key: group.key, label: group.label, actions, resources, permissionCount };
        })
        .filter((group) => group.resources.length > 0);
}

function grantedActionsFor(resource: CatalogResourceType, grants: RoleGrants): Set<ActionCode> {
    if (grants === '*') return new Set(resource.applicable_actions);
    const roleActions = grants[resource.code] ?? [];
    return new Set(resource.applicable_actions.filter((action) => roleActions.includes(action)));
}
