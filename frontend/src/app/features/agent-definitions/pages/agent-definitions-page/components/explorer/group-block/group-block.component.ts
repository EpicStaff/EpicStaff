import { Component, computed, effect, ElementRef, inject, input, output, signal, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, getLabelColorOption, ResourceCode } from '@shared/models';

import { ExplorerSelection, GroupAssignTarget } from '../../../../../models/explorer.model';
import { BranchTreeNode, ExplorerGroupBlock, GroupedSectionId, nodeKey } from '../../../../../models/tree-node.model';
import { AgentDragService } from '../../../../../services/agent-drag.service';
import { AgentsPageStore } from '../../../../../services/agents-page-store.service';
import { SurfaceDragService } from '../../../../../services/surface-drag.service';
import { GroupHeaderMenuSubject } from '../explorer-context-menu/explorer-menu.model';
import { GROUP_MENU_ACTION, menuPositionFromClick } from '../explorer-menu.util';
import {
    ExplorerTreeAttachSurfaceEvent,
    ExplorerTreeMenuEvent,
    ExplorerTreeMenuOpenEvent,
    TreeNodeComponent,
} from '../tree-node/tree-node.component';

/**
 * One group of the Agents or Shared Surfaces section: a sticky header (color dot, name, count) over
 * its rows. The whole block is a drop target: dropping the section's kind of item on the header or on
 * any of its rows moves the item into the group (Ungrouped: out of any group).
 */
@Component({
    selector: 'app-explorer-group-block',
    imports: [AppSvgIconComponent, HasPermissionDirective, MatTooltipModule, TreeNodeComponent],
    templateUrl: './group-block.component.html',
    styleUrls: ['./group-block.component.scss'],
})
export class ExplorerGroupBlockComponent {
    readonly block = input.required<ExplorerGroupBlock>();
    readonly section = input.required<GroupedSectionId>();
    readonly selected = input.required<ExplorerSelection>();

    readonly selectNode = output<BranchTreeNode>();
    readonly menuAction = output<ExplorerTreeMenuEvent>();
    readonly menuOpen = output<ExplorerTreeMenuOpenEvent>();
    readonly attachSurface = output<ExplorerTreeAttachSurfaceEvent>();

    private readonly renameInput = viewChild<ElementRef<HTMLInputElement>>('renameInput');

    protected readonly dropActive = signal<boolean>(false);

    protected readonly collapsed = computed<boolean>(() =>
        this.store.isGroupCollapsed(this.section(), this.block().groupId)
    );

    protected readonly renaming = computed<boolean>(() => {
        const groupId = this.block().groupId;
        return groupId !== null && this.store.renamingGroupId() === groupId;
    });

    protected readonly dotColor = computed<string | null>(() => {
        const color = this.block().color;
        return color === null ? null : getLabelColorOption(color).circleBg;
    });

    /** The dragged item this block accepts: an agent in the Agents section, a shared surface in Shared Surfaces. */
    private readonly droppable = computed<GroupAssignTarget | null>(() => {
        if (this.section() === 'agents') {
            const agent = this.agentDrag.dragged();
            return agent ? { kind: 'agent', id: agent.id } : null;
        }
        const surface = this.surfaceDrag.dragged();
        return surface ? { kind: 'surface', id: surface.id } : null;
    });

    /** An empty Ungrouped is hidden, except as a drop target while an item is dragged. */
    protected readonly hidden = computed<boolean>(() => {
        const block = this.block();
        return block.groupId === null && block.memberCount === 0 && this.droppable() === null;
    });

    protected readonly showEmptyHint = computed<boolean>(() => {
        const block = this.block();
        return this.section() === 'agents' && block.groupId !== null && block.memberCount === 0;
    });

    private readonly focusRenameInput = effect(() => {
        const input = this.renameInput()?.nativeElement;
        if (!input) return;
        input.focus();
        input.select();
    });

    protected readonly trackByKey = (_: number, node: BranchTreeNode) => nodeKey(node);
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    private readonly store = inject(AgentsPageStore);
    private readonly agentDrag = inject(AgentDragService);
    private readonly surfaceDrag = inject(SurfaceDragService);

    protected toggle(): void {
        this.store.toggleGroupCollapsed(this.section(), this.block().groupId);
    }

    protected onMenuClick(event: MouseEvent): void {
        event.stopPropagation();
        const subject = this.menuSubject();
        if (!subject) return;
        this.menuOpen.emit({
            node: subject,
            items: [],
            position: menuPositionFromClick(event),
            trigger: event.currentTarget as HTMLElement,
        });
    }

    protected onAddAgent(event: MouseEvent): void {
        event.stopPropagation();
        const subject = this.menuSubject();
        if (!subject) return;
        this.menuAction.emit({
            node: subject,
            action: GROUP_MENU_ACTION.newAgentInGroup,
            trigger: event.currentTarget as HTMLElement,
        });
    }

    protected commitRename(name: string): void {
        const groupId = this.block().groupId;
        // Escape already ended the rename; the blur that follows must not save it.
        if (groupId === null || !this.renaming()) return;
        this.store.renameGroup(groupId, name);
    }

    protected cancelRename(): void {
        this.store.cancelRenameGroup();
    }

    protected onDragOver(event: DragEvent): void {
        if (!this.droppable()) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        this.dropActive.set(true);
    }

    protected onDragLeave(event: DragEvent): void {
        const host = event.currentTarget as HTMLElement;
        const related = event.relatedTarget as Node | null;
        if (related && host.contains(related)) return;
        this.dropActive.set(false);
    }

    protected onDrop(event: DragEvent): void {
        this.dropActive.set(false);
        const item = this.droppable();
        if (!item) return;
        event.preventDefault();
        this.agentDrag.end();
        this.surfaceDrag.end();
        this.store.moveToGroup(item, this.block().groupId);
    }

    private menuSubject(): GroupHeaderMenuSubject | null {
        const groupId = this.block().groupId;
        return groupId === null ? null : { kind: 'group-header', section: this.section(), groupId };
    }
}
