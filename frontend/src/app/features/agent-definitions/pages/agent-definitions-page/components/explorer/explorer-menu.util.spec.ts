import { LabelColor, LabelDto } from '@shared/models';

import { ExplorerMenuItem, ExplorerMenuSubject } from './explorer-context-menu/explorer-menu.model';
import { groupMenuItems } from './explorer-menu.util';

const SALES = 1;
const SUPPORT = 2;

function group(id: number, name: string, color: LabelColor): LabelDto {
    return { id, name, parent: null, full_path: name, created_at: '', metadata: { color } };
}

const GROUPS = [group(SALES, 'Sales', LabelColor.Blue), group(SUPPORT, 'Support', LabelColor.Green)];

/** Each item as its label, an expandable one followed by its children; a disabled child is marked "(current)". */
const outline = (items: ExplorerMenuItem[]): string[] =>
    items.map((item) => (item.children ? `${item.label} > ${item.children.map(childLabel).join(', ')}` : item.label));

const childLabel = (child: ExplorerMenuItem): string => `${child.label}${child.disabled ? ' (current)' : ''}`;

describe('groupMenuItems', () => {
    it.each<[string, ExplorerMenuSubject, LabelDto[], string[]]>([
        [
            'an ungrouped agent: every group, no Ungrouped',
            { kind: 'agent', agentId: 5, label: 'Closer', children: [], groupId: null },
            GROUPS,
            ['Move to group > Sales, Support', 'New group…'],
        ],
        [
            'an agent in a group: the other groups, then Ungrouped',
            { kind: 'agent', agentId: 5, label: 'Closer', children: [], groupId: SALES },
            GROUPS,
            ['Move to group > Support, Ungrouped', 'New group…'],
        ],
        [
            'an ungrouped agent with no groups yet: only New group',
            { kind: 'agent', agentId: 5, label: 'Closer', children: [], groupId: null },
            [],
            ['New group…'],
        ],
        [
            'a shared surface in a group: the other groups, then Ungrouped',
            { kind: 'surface', surfaceId: 10, label: 'CRM access', groupId: SUPPORT },
            GROUPS,
            ['Move to group > Sales, Ungrouped', 'New group…'],
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
            'an Agents group header: its current color disabled',
            { kind: 'group-header', section: 'agents', groupId: SALES },
            GROUPS,
            [
                'New agent in Sales',
                'Rename',
                'Color > Default, Purple, Blue (current), Green, Orange, Red',
                'Delete group',
            ],
        ],
        [
            'a Shared Surfaces group header: no New agent',
            { kind: 'group-header', section: 'surfaces', groupId: SUPPORT },
            GROUPS,
            ['Rename', 'Color > Default, Purple, Blue, Green (current), Orange, Red', 'Delete group'],
        ],
    ])('%s', (_description, subject, groups, expected) => {
        expect(outline(groupMenuItems(subject, groups))).toEqual(expected);
    });
});
