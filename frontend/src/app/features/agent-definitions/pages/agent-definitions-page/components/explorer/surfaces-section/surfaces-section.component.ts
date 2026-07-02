import { ChangeDetectionStrategy, Component, inject, output } from '@angular/core';

import { BranchTreeNode, nodeKey } from '../../../../../models/tree-node.model';
import { AgentsPageStore } from '../../../../../services/agents-page-store.service';
import { ExplorerTreeMenuEvent, ExplorerTreeMenuOpenEvent, TreeNodeComponent } from '../tree-node/tree-node.component';

@Component({
    selector: 'app-surfaces-section',
    imports: [TreeNodeComponent],
    templateUrl: './surfaces-section.component.html',
    styleUrls: ['./surfaces-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfacesSectionComponent {
    protected readonly store: AgentsPageStore = inject(AgentsPageStore);

    selectNode = output<BranchTreeNode>();
    menuAction = output<ExplorerTreeMenuEvent>();
    menuOpen = output<ExplorerTreeMenuOpenEvent>();

    readonly trackByKey = (_: number, n: BranchTreeNode) => nodeKey(n);

    onSelect(node: BranchTreeNode): void {
        this.selectNode.emit(node);
    }

    onMenuAction(event: ExplorerTreeMenuEvent): void {
        this.menuAction.emit(event);
    }

    onMenuOpen(event: ExplorerTreeMenuOpenEvent): void {
        this.menuOpen.emit(event);
    }
}
