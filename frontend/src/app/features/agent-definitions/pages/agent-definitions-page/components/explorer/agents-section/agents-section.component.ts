import { HttpErrorResponse } from '@angular/common/http';
import {
    afterRenderEffect,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    inject,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { ButtonComponent, FetchErrorStateComponent } from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';

import { BranchTreeNode, nodeKey } from '../../../../../models/tree-node.model';
import { AgentsPageStore } from '../../../../../services/agents-page-store.service';
import { ExplorerGroupBlockComponent } from '../group-block/group-block.component';
import {
    ExplorerTreeAttachSurfaceEvent,
    ExplorerTreeMenuEvent,
    ExplorerTreeMenuOpenEvent,
    TreeNodeComponent,
} from '../tree-node/tree-node.component';

@Component({
    selector: 'app-agents-section',
    imports: [TreeNodeComponent, FetchErrorStateComponent, ExplorerGroupBlockComponent, ButtonComponent],
    templateUrl: './agents-section.component.html',
    styleUrls: ['./agents-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentsSectionComponent {
    selectNode = output<BranchTreeNode>();
    menuAction = output<ExplorerTreeMenuEvent>();
    menuOpen = output<ExplorerTreeMenuOpenEvent>();
    attachSurface = output<ExplorerTreeAttachSurfaceEvent>();

    private readonly newGroupInput = viewChild<ElementRef<HTMLInputElement>>('newGroupInput');

    protected readonly newGroupError = signal<string | null>(null);
    protected readonly creatingGroup = signal<boolean>(false);

    private readonly focusNewGroupInput = afterRenderEffect(() => this.newGroupInput()?.nativeElement.focus());

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

    protected createGroup(name: string, refocusOnError = true): void {
        const draft = this.store.newGroupDraft();
        if (!draft || this.creatingGroup()) return;
        if (!name.trim()) {
            this.cancelNewGroup();
            return;
        }
        this.creatingGroup.set(true);
        this.store.createGroup(name, draft.assign).subscribe({
            next: () => {
                this.creatingGroup.set(false);
                this.cancelNewGroup();
            },
            error: (err: HttpErrorResponse) => {
                this.creatingGroup.set(false);
                this.newGroupError.set(extractHttpErrorMessage(err, 'Failed to create group'));
                // Disabling the input dropped its focus; give it back so the name can be fixed.
                // Not after a blur save: the user has moved on, and stealing focus back would trap them.
                if (refocusOnError) setTimeout(() => this.newGroupInput()?.nativeElement.focus());
            },
        });
    }

    protected cancelNewGroup(): void {
        this.newGroupError.set(null);
        this.store.cancelNewGroup();
    }

    /**
     * Leaving the input saves a typed name and cancels an empty one. While an error is
     * shown the draft stays as is, so blur never resubmits a name the server just rejected.
     */
    protected onNewGroupBlur(name: string): void {
        if (this.creatingGroup() || this.newGroupError()) return;
        if (!name.trim()) {
            this.cancelNewGroup();
            return;
        }
        this.createGroup(name, false);
    }
}
