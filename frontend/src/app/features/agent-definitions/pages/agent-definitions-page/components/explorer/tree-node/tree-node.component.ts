import { ChangeDetectionStrategy, Component, computed, input, OnInit, output, signal } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { ExplorerSelection } from '../../../../../models/explorer.model';
import { BranchTreeNode, nodeKey } from '../../../../../models/tree-node.model';
import { ExplorerMenuItem, ExplorerMenuPosition } from '../explorer-context-menu/explorer-menu.model';
import { menuPositionFromClick, treeNodeMenuItems } from '../explorer-menu.util';

export interface ExplorerTreeMenuEvent {
    node: BranchTreeNode;
    action: string;
}

export interface ExplorerTreeMenuOpenEvent {
    node: BranchTreeNode;
    items: ExplorerMenuItem[];
    position: ExplorerMenuPosition;
}

@Component({
    selector: 'app-tree-node',
    imports: [AppSvgIconComponent],
    templateUrl: './tree-node.component.html',
    styleUrls: ['./tree-node.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TreeNodeComponent implements OnInit {
    node = input.required<BranchTreeNode>();
    depth = input(0);
    selected = input<ExplorerSelection>({ kind: null, id: null });

    selectNode = output<BranchTreeNode>();
    menuAction = output<ExplorerTreeMenuEvent>();
    menuOpen = output<ExplorerTreeMenuOpenEvent>();

    expanded = false;
    readonly hovered = signal(false);

    ngOnInit(): void {
        const n = this.node();
        if (n.kind === 'group') this.expanded = !!n.defaultExpanded;
        else if (n.kind === 'agent') this.expanded = false;
    }

    readonly trackByKey = (_: number, n: BranchTreeNode) => nodeKey(n);

    readonly isSelected = computed(() => {
        const n = this.node();
        const sel = this.selected();
        if (n.kind === 'surface') {
            return (
                sel.kind === 'surface' &&
                sel.id === n.surfaceId &&
                (sel.ownerAgentId ?? null) === (n.ownerAgentId ?? null)
            );
        }
        if (n.kind === 'agent') {
            return sel.kind === 'agent' && sel.id === n.agentId;
        }
        if (n.kind === 'agent-doc') {
            return sel.kind === 'agent-doc' && sel.id === n.agentId && sel.docType === n.docType;
        }
        return false;
    });

    readonly hasChildren = computed(() => {
        const n = this.node();
        return (n.kind === 'group' && n.children.length > 0) || (n.kind === 'agent' && n.children.length > 0);
    });

    readonly childIndent = computed(() => this.depth() + 1);

    private readonly hoverMenuItems = computed(() => treeNodeMenuItems(this.node()));

    readonly showHoverMenu = computed(() => this.hoverMenuItems().length > 0);

    toggle(): void {
        this.expanded = !this.expanded;
    }

    onRowClick(): void {
        this.selectNode.emit(this.node());
    }

    onChevron(event: Event): void {
        event.stopPropagation();
        this.toggle();
    }

    onChildSelect(node: BranchTreeNode): void {
        this.selectNode.emit(node);
    }

    onChildMenuAction(event: ExplorerTreeMenuEvent): void {
        this.menuAction.emit(event);
    }

    onChildMenuOpen(event: ExplorerTreeMenuOpenEvent): void {
        this.menuOpen.emit(event);
    }

    onMouseEnter(): void {
        this.hovered.set(true);
    }

    onMouseLeave(): void {
        this.hovered.set(false);
    }

    onMenuClick(event: MouseEvent): void {
        event.stopPropagation();
        const items = this.hoverMenuItems();
        if (!items.length) return;
        this.menuOpen.emit({ node: this.node(), items, position: menuPositionFromClick(event) });
    }
}
