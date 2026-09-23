import { ActionCode, ResourceCode } from '@shared/models';

import { BranchTreeNode } from '../../../../models/tree-node.model';
import { ExplorerMenuItem } from './explorer-context-menu/explorer-menu.model';

export function treeNodeMenuItems(node: BranchTreeNode): ExplorerMenuItem[] {
    switch (node.kind) {
        case 'agent':
            return [
                { id: 'duplicate', label: 'Duplicate', resource: ResourceCode.Agents, action: ActionCode.Create },
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
