import { ChangeDetectionStrategy, Component, inject, output } from '@angular/core';
import { ButtonComponent, FetchErrorStateComponent } from '@shared/components';

import { BranchTreeNode, nodeKey } from '../../../../../models/tree-node.model';
import { AgentsPageStore } from '../../../../../services/agents-page-store.service';
import { ExplorerGroupBlockComponent } from '../group-block/group-block.component';
import { NewGroupInputComponent } from '../new-group-input/new-group-input.component';
import {
    ExplorerTreeAttachSurfaceEvent,
    ExplorerTreeMenuEvent,
    ExplorerTreeMenuOpenEvent,
    TreeNodeComponent,
} from '../tree-node/tree-node.component';

@Component({
    selector: 'app-agents-section',
    imports: [
        TreeNodeComponent,
        FetchErrorStateComponent,
        ExplorerGroupBlockComponent,
        ButtonComponent,
        NewGroupInputComponent,
    ],
    templateUrl: './agents-section.component.html',
    styleUrls: ['./agents-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentsSectionComponent {
    selectNode = output<BranchTreeNode>();
    menuAction = output<ExplorerTreeMenuEvent>();
    menuOpen = output<ExplorerTreeMenuOpenEvent>();
    attachSurface = output<ExplorerTreeAttachSurfaceEvent>();

    readonly trackByKey = (_: number, n: BranchTreeNode) => nodeKey(n);

    protected readonly store: AgentsPageStore = inject(AgentsPageStore);

    onSelect(node: BranchTreeNode): void {
        this.selectNode.emit(node);
    }

    onMenuAction(event: ExplorerTreeMenuEvent): void {
        this.menuAction.emit(event);
    }

    onMenuOpen(event: ExplorerTreeMenuOpenEvent): void {
        this.menuOpen.emit(event);
    }

    onAttachSurface(event: ExplorerTreeAttachSurfaceEvent): void {
        this.attachSurface.emit(event);
    }
}
