import { BranchTreeNode } from '../../../../models/tree-node.model';
import { ExplorerMenuItem } from './explorer-context-menu/explorer-menu.model';

export function treeNodeMenuItems(node: BranchTreeNode): ExplorerMenuItem[] {
    switch (node.kind) {
        case 'agent':
            return [
                { id: 'duplicate', label: 'Duplicate' },
                { id: 'delete', label: 'Delete' },
            ];
        case 'surface':
            if (node.ownerAgentId == null) {
                return [
                    { id: 'duplicate', label: 'Duplicate' },
                    { id: 'delete', label: 'Delete' },
                ];
            }
            if (node.locked) {
                return [
                    { id: 'duplicate', label: 'Duplicate' },
                    { id: 'delete', label: 'Delete' },
                ];
            }
            return [
                { id: 'open-source', label: 'Open in Shared Surfaces' },
                { id: 'detach', label: 'Detach from agent' },
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
