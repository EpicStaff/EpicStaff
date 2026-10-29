import { ActionCode, getLabelColorOption, LABEL_COLOR_OPTIONS, LabelDto, ResourceCode } from '@shared/models';

import { BranchTreeNode } from '../../../../models/tree-node.model';
import { ExplorerMenuItem, ExplorerMenuSubject } from './explorer-context-menu/explorer-menu.model';

/** Menu action ids for groups. Ids carrying a value are `<prefix><value>`. */
export const GROUP_MENU_ACTION = {
    moveToGroupPrefix: 'move-to-group:',
    /** Value of `moveToGroupPrefix` meaning "no group". */
    ungrouped: 'ungrouped',
    newGroup: 'new-group',
    newAgentInGroup: 'new-agent-in-group',
    renameGroup: 'rename-group',
    groupColorPrefix: 'group-color:',
    deleteGroup: 'delete-group',
    collapseAll: 'collapse-all',
    expandAll: 'expand-all',
} as const;

/**
 * The group items of a menu (shown before the row's own items): "Move to group" and "New group…" on
 * an agent or a shared surface, the group actions on a group header, and the Agents section menu.
 * Groups are managed under the Agents permission, like their `agent-labels/` endpoint.
 */
export function groupMenuItems(subject: ExplorerMenuSubject, groups: LabelDto[]): ExplorerMenuItem[] {
    switch (subject.kind) {
        case 'agent':
            return itemGroupMenuItems(subject.groupId ?? null, groups, ResourceCode.Agents);
        case 'surface':
            // Owned surfaces, and shared ones shown under an agent, follow the agent: not groupable here.
            return subject.ownerAgentId == null
                ? itemGroupMenuItems(subject.groupId ?? null, groups, ResourceCode.Surfaces)
                : [];
        case 'group-header': {
            const group = groups.find((candidate) => candidate.id === subject.groupId);
            if (!group) return [];
            const items: ExplorerMenuItem[] = [];
            if (subject.section === 'agents') {
                items.push({
                    id: GROUP_MENU_ACTION.newAgentInGroup,
                    label: `New agent in ${group.name}`,
                    resource: ResourceCode.Agents,
                    action: ActionCode.Create,
                });
            }
            items.push(
                {
                    id: GROUP_MENU_ACTION.renameGroup,
                    label: 'Rename',
                    resource: ResourceCode.Agents,
                    action: ActionCode.Update,
                },
                {
                    id: 'group-color',
                    label: 'Color',
                    resource: ResourceCode.Agents,
                    action: ActionCode.Update,
                    children: LABEL_COLOR_OPTIONS.map((option) => ({
                        id: GROUP_MENU_ACTION.groupColorPrefix + option.id,
                        label: option.id.charAt(0).toUpperCase() + option.id.slice(1),
                        resource: ResourceCode.Agents,
                        action: ActionCode.Update,
                        dotColor: option.circleBg,
                        disabled: (group.metadata?.color ?? LABEL_COLOR_OPTIONS[0].id) === option.id,
                    })),
                },
                {
                    id: GROUP_MENU_ACTION.deleteGroup,
                    label: 'Delete group',
                    resource: ResourceCode.Agents,
                    action: ActionCode.Delete,
                    danger: true,
                }
            );
            return items;
        }
        case 'section-header': {
            const items: ExplorerMenuItem[] = [
                {
                    id: GROUP_MENU_ACTION.newGroup,
                    label: 'New group',
                    resource: ResourceCode.Agents,
                    action: ActionCode.Create,
                },
            ];
            if (groups.length > 0) {
                items.push(
                    {
                        id: GROUP_MENU_ACTION.collapseAll,
                        label: 'Collapse all',
                        resource: ResourceCode.Agents,
                        action: ActionCode.Read,
                    },
                    {
                        id: GROUP_MENU_ACTION.expandAll,
                        label: 'Expand all',
                        resource: ResourceCode.Agents,
                        action: ActionCode.Read,
                    }
                );
            }
            return items;
        }
        default:
            return [];
    }
}

/** "Move to group" (every other group, then Ungrouped when grouped) and "New group…". */
function itemGroupMenuItems(
    currentGroupId: number | null,
    groups: LabelDto[],
    resource: ResourceCode
): ExplorerMenuItem[] {
    const targets: ExplorerMenuItem[] = groups
        .filter((group) => group.id !== currentGroupId)
        .map((group) => ({
            id: GROUP_MENU_ACTION.moveToGroupPrefix + group.id,
            label: group.name,
            resource,
            action: ActionCode.Update,
            dotColor: getLabelColorOption(group.metadata?.color).circleBg,
        }));
    if (currentGroupId !== null) {
        targets.push({
            id: GROUP_MENU_ACTION.moveToGroupPrefix + GROUP_MENU_ACTION.ungrouped,
            label: 'Ungrouped',
            resource,
            action: ActionCode.Update,
            dotColor: null,
        });
    }
    const items: ExplorerMenuItem[] = [];
    if (targets.length > 0) {
        items.push({
            id: 'move-to-group',
            label: 'Move to group',
            resource,
            action: ActionCode.Update,
            children: targets,
        });
    }
    // Creating a group needs Agents:Create; moving the item into it needs `resource`:Update, checked by its PATCH.
    items.push({
        id: GROUP_MENU_ACTION.newGroup,
        label: 'New group…',
        resource: ResourceCode.Agents,
        action: ActionCode.Create,
    });
    return items;
}

export function treeNodeMenuItems(node: BranchTreeNode): ExplorerMenuItem[] {
    switch (node.kind) {
        case 'agent':
            return [
                { id: 'duplicate', label: 'Duplicate', resource: ResourceCode.Agents, action: ActionCode.Create },
                // Authorship is read-only, so seeing the agent is enough to see who created and edited it.
                { id: 'view-details', label: 'View Details', resource: ResourceCode.Agents, action: ActionCode.Read },
                { id: 'delete', label: 'Delete', resource: ResourceCode.Agents, action: ActionCode.Delete },
            ];
        case 'surface':
            if (node.ownerAgentId == null) {
                return [
                    { id: 'duplicate', label: 'Duplicate', resource: ResourceCode.Surfaces, action: ActionCode.Create },
                    { id: 'delete', label: 'Delete', resource: ResourceCode.Surfaces, action: ActionCode.Delete },
                ];
            }
            if (node.locked) {
                return [
                    { id: 'duplicate', label: 'Duplicate', resource: ResourceCode.Surfaces, action: ActionCode.Create },
                    { id: 'delete', label: 'Delete', resource: ResourceCode.Surfaces, action: ActionCode.Delete },
                ];
            }
            return [
                {
                    id: 'open-source',
                    resource: ResourceCode.Surfaces,
                    action: ActionCode.Read,
                    label: 'Open in Shared Surfaces',
                },
                // Detaching surface requires Update permission for Agents, not the Surfaces
                { id: 'detach', resource: ResourceCode.Agents, action: ActionCode.Update, label: 'Detach from agent' },
            ];
        default:
            return [];
    }
}

export function menuPositionFromClick(event: MouseEvent, menuWidth = 170): { x: number; y: number } {
    const target = event.currentTarget as HTMLElement;
    const rect = target.getBoundingClientRect();
    return {
        x: Math.min(rect.left, window.innerWidth - menuWidth - 8),
        y: rect.bottom + 4,
    };
}
