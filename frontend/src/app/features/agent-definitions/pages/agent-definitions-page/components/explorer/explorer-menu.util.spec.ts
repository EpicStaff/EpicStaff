import { ActionCode, LabelDto, ResourceCode } from '@shared/models';

import { Surface } from '../../../../models/surface.model';
import { BranchTreeNode } from '../../../../models/tree-node.model';
import { ExplorerMenuItem, ExplorerMenuSubject } from './explorer-context-menu/explorer-menu.model';
import {
    AGENTS_SECTION_MENU_ACTION,
    agentsSectionMenuItems,
    canDuplicateAgent,
    groupMenuItems,
    isTreeNodeMenuItemAllowed,
    treeNodeMenuItems,
} from './explorer-menu.util';

const SALES = 1;
const SUPPORT = 2;

function group(id: number, name: string): LabelDto {
    return { id, name, parent: null, full_path: name, created_at: '', metadata: {} };
}

const GROUPS = [group(SALES, 'Sales'), group(SUPPORT, 'Support')];

/** Each item as its label, an expandable one followed by its children's labels. */
const outline = (items: ExplorerMenuItem[]): string[] =>
    items.map((item) =>
        item.children ? `${item.label} > ${item.children.map((child) => child.label).join(', ')}` : item.label
    );

describe('groupMenuItems', () => {
    it.each<[string, ExplorerMenuSubject, LabelDto[], string[]]>([
        [
            'an ungrouped agent: every group, without No group',
            { kind: 'agent', agentId: 5, label: 'Closer', children: [], groupId: null },
            GROUPS,
            ['Move to group > Sales, Support', 'New group…'],
        ],
        [
            'an agent in a group: the other groups, then No group',
            { kind: 'agent', agentId: 5, label: 'Closer', children: [], groupId: SALES },
            GROUPS,
            ['Move to group > Support, No group', 'New group…'],
        ],
        [
            'an ungrouped agent with no groups yet: only New group',
            { kind: 'agent', agentId: 5, label: 'Closer', children: [], groupId: null },
            [],
            ['New group…'],
        ],
        [
            'a shared surface in a group: the other groups, then No group',
            { kind: 'surface', surfaceId: 10, label: 'CRM access', groupId: SUPPORT },
            GROUPS,
            ['Move to group > Sales, No group', 'New group…'],
        ],
        [
            "an agent's owned surface: nothing, it follows its agent",
            { kind: 'surface', surfaceId: 12, label: 'Qualify in chat', ownerAgentId: 5 },
            GROUPS,
            [],
        ],
        [
            'a shared surface shown under an agent: nothing, it follows that agent',
            { kind: 'surface', surfaceId: 10, label: 'CRM access', ownerAgentId: 5, shared: true, groupId: SUPPORT },
            GROUPS,
            [],
        ],
        [
            'an Agents group header: New agent, Rename, Ungroup',
            { kind: 'group-header', section: 'agents', groupId: SALES },
            GROUPS,
            ['New agent in Sales', 'Rename', 'Ungroup'],
        ],
        [
            'a Shared Surfaces group header: no New agent',
            { kind: 'group-header', section: 'surfaces', groupId: SUPPORT },
            GROUPS,
            ['Rename', 'Ungroup'],
        ],
    ])('%s', (_description, subject, groups, expected) => {
        expect(outline(groupMenuItems(subject, groups))).toEqual(expected);
    });
});

describe('agentsSectionMenuItems', () => {
    it('offers Import to whoever can create agents and Export… to whoever can export them', () => {
        expect(agentsSectionMenuItems()).toEqual([
            {
                id: AGENTS_SECTION_MENU_ACTION.import,
                label: 'Import',
                resource: ResourceCode.Agents,
                action: ActionCode.Create,
            },
            {
                id: AGENTS_SECTION_MENU_ACTION.export,
                label: 'Export…',
                resource: ResourceCode.Agents,
                action: ActionCode.Export,
            },
        ]);
    });
});

const AGENT_CREATE = `${ResourceCode.Agents}:${ActionCode.Create}`;
const SURFACE_CREATE = `${ResourceCode.Surfaces}:${ActionCode.Create}`;
const AGENT_READ = `${ResourceCode.Agents}:${ActionCode.Read}`;

/** A user holding exactly the given `resource:action` permissions. */
const userWith = (...granted: string[]) => ({
    can: (resource: ResourceCode, action: ActionCode): boolean => granted.includes(`${resource}:${action}`),
});

const READER = 3;
const OTHER_AGENT = 4;

function surfaceOwnedBy(id: number, ownerAgentId: number | null): Surface {
    return { id, name: `Surface ${id}`, group: null, owner_agent: ownerAgentId } as Partial<Surface> as Surface;
}

describe('canDuplicateAgent', () => {
    it.each<[string, Surface[], string[], boolean]>([
        ['an agent owning no surface, with Agents:Create', [], [AGENT_CREATE], true],
        ['an agent owning no surface, without Agents:Create', [], [SURFACE_CREATE], false],
        [
            'an agent owning a surface, with Agents:Create and Surfaces:Create',
            [surfaceOwnedBy(20, READER)],
            [AGENT_CREATE, SURFACE_CREATE],
            true,
        ],
        ['an agent owning a surface, without Surfaces:Create', [surfaceOwnedBy(20, READER)], [AGENT_CREATE], false],
        ['an agent owning a surface, without Agents:Create', [surfaceOwnedBy(20, READER)], [SURFACE_CREATE], false],
        [
            'only shared surfaces and surfaces of another agent, without Surfaces:Create',
            [surfaceOwnedBy(20, null), surfaceOwnedBy(21, OTHER_AGENT)],
            [AGENT_CREATE],
            true,
        ],
    ])('%s', (_description, surfaces, granted, expected) => {
        expect(canDuplicateAgent(READER, surfaces, userWith(...granted))).toBe(expected);
    });
});

describe('isTreeNodeMenuItemAllowed', () => {
    const readerNode: BranchTreeNode = { kind: 'agent', agentId: READER, label: 'Invoice Reader', children: [] };
    const allowedLabels = (surfaces: Surface[], granted: string[]): string[] =>
        treeNodeMenuItems(readerNode)
            .filter((item) => isTreeNodeMenuItemAllowed(readerNode, item, surfaces, userWith(...granted)))
            .map((item) => item.label);

    it('drops Duplicate from the menu of an agent owning a surface when the user cannot create surfaces', () => {
        expect(allowedLabels([surfaceOwnedBy(20, READER)], [AGENT_CREATE, AGENT_READ])).toEqual(['View Details']);
    });

    it('keeps Duplicate in the menu of an agent owning no surface', () => {
        expect(allowedLabels([surfaceOwnedBy(20, OTHER_AGENT)], [AGENT_CREATE, AGENT_READ])).toEqual([
            'Duplicate',
            'View Details',
        ]);
    });
});
