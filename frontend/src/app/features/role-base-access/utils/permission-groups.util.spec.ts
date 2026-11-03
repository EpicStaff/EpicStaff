import { ActionCode, CatalogResponse, ResourceCode } from '@shared/models';

import { buildGrantedPermissionGroups, groupCatalogResources, RoleGrants } from './permission-groups.util';

function resource(code: ResourceCode, group: string, applicableActions: ActionCode[]) {
    return {
        code,
        label: code,
        group,
        description: '',
        applicable_actions: applicableActions,
        platform_actions: [],
        recommended_with: {} as CatalogResponse['resource_types'][number]['recommended_with'],
    };
}

const catalog: CatalogResponse = {
    actions: [
        { code: ActionCode.Create, label: 'Create', bit: 1 },
        { code: ActionCode.Read, label: 'Read', bit: 2 },
        { code: ActionCode.Update, label: 'Update', bit: 4 },
        { code: ActionCode.Delete, label: 'Delete', bit: 8 },
        { code: ActionCode.Use, label: 'Use', bit: 16 },
    ],
    resource_types: [
        resource(ResourceCode.Roles, 'admin', [ActionCode.Create, ActionCode.Read, ActionCode.Update]),
        resource(ResourceCode.Flows, 'workspace', [ActionCode.Read, ActionCode.Update, ActionCode.Use]),
        resource(ResourceCode.Agents, 'workspace', [ActionCode.Create, ActionCode.Read, ActionCode.Delete]),
        resource(ResourceCode.Secrets, 'config', [ActionCode.Read, ActionCode.Use]),
    ],
};

/** Flattens the result to `group: resource[actions] …` with the group's visible columns, for readable tables. */
function summarize(grants: RoleGrants): string[] {
    return buildGrantedPermissionGroups(catalog, grants).map((group) => {
        const columns = group.actions.map((action) => action.code).join(',');
        const rows = group.resources
            .map((entry) => `${entry.resource.code}[${[...entry.grantedActions].join(',')}]`)
            .join(' ');
        return `${group.key} (${group.permissionCount}) cols=${columns}: ${rows}`;
    });
}

describe('buildGrantedPermissionGroups', () => {
    it.each<[string, RoleGrants, string[]]>([
        ['a role with no permissions shows nothing', {}, []],
        [
            'resources and groups without a granted action are hidden',
            { [ResourceCode.Flows]: [ActionCode.Read] },
            ['workspace (1) cols=read: flows[read]'],
        ],
        [
            'a column appears when any visible resource of the group has that action',
            {
                [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Use],
                [ResourceCode.Agents]: [ActionCode.Delete],
            },
            ['workspace (3) cols=read,delete,use: flows[read,use] agents[delete]'],
        ],
        [
            'columns are per group, not shared across groups',
            { [ResourceCode.Roles]: [ActionCode.Create], [ResourceCode.Secrets]: [ActionCode.Use] },
            ['admin (1) cols=create: roles[create]', 'config (1) cols=use: secrets[use]'],
        ],
        [
            'actions the catalog does not list as applicable are ignored',
            { [ResourceCode.Secrets]: [ActionCode.Delete], [ResourceCode.Roles]: [ActionCode.Read] },
            ['admin (1) cols=read: roles[read]'],
        ],
        ['an empty action list counts as not granted', { [ResourceCode.Agents]: [] }, []],
        [
            'the superadmin wildcard grants every applicable action',
            '*',
            [
                'admin (3) cols=create,read,update: roles[create,read,update]',
                'workspace (6) cols=create,read,update,delete,use: flows[read,update,use] agents[create,read,delete]',
                'config (2) cols=read,use: secrets[read,use]',
            ],
        ],
    ])('%s', (_case, grants, expected) => {
        expect(summarize(grants)).toEqual(expected);
    });

    it('groups resources by group in first-seen catalog order, labelling an unknown group with its key', () => {
        const withUnknownGroup: CatalogResponse = {
            ...catalog,
            resource_types: [
                resource(ResourceCode.Venvs, 'sandbox', [ActionCode.Read]),
                ...catalog.resource_types,
                resource(ResourceCode.Files, 'sandbox', [ActionCode.Read]),
            ],
        };

        const groups = groupCatalogResources(withUnknownGroup);

        expect(groups.map((group) => [group.key, group.resources.map((entry) => entry.code)])).toEqual([
            ['sandbox', [ResourceCode.Venvs, ResourceCode.Files]],
            ['admin', [ResourceCode.Roles]],
            ['workspace', [ResourceCode.Flows, ResourceCode.Agents]],
            ['config', [ResourceCode.Secrets]],
        ]);
        expect(groups[0].label).toBe('sandbox');
    });
});
