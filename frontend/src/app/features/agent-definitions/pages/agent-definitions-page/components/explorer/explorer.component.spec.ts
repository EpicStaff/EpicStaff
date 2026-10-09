import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { SectionHeightService, SidebarWidthService } from '@shared/services';

import { StorageDragService } from '../../../../../files/services/storage-drag.service';
import { BranchTreeNode } from '../../../../models/tree-node.model';
import { AgentsPageStore } from '../../../../services/agents-page-store.service';
import { SurfaceDragService } from '../../../../services/surface-drag.service';
import { ExplorerComponent } from './explorer.component';
import { ExplorerContextMenuComponent } from './explorer-context-menu/explorer-context-menu.component';
import { ExplorerTreeMenuEvent } from './tree-node/tree-node.component';

const AGENT_NODE: BranchTreeNode = { kind: 'agent', agentId: 3, label: 'CV Processor', children: [] };

function render(): {
    fixture: ComponentFixture<ExplorerComponent>;
    host: HTMLElement;
    actions: ExplorerTreeMenuEvent[];
} {
    TestBed.configureTestingModule({
        providers: [
            { provide: AgentsPageStore, useValue: { isSectionExpanded: () => false, isSectionVisible: () => true } },
            { provide: StorageDragService, useValue: { isDragging: signal(false) } },
            { provide: SurfaceDragService, useValue: { isDragging: signal(false) } },
            { provide: SidebarWidthService, useValue: { getWidth: () => signal(280) } },
            { provide: SectionHeightService, useValue: { getHeight: () => signal(null), setHeight: () => undefined } },
        ],
    });
    // Only the row menu is under test: the sections that open it are covered by the tree-node spec.
    TestBed.overrideComponent(ExplorerComponent, {
        set: {
            imports: [ExplorerContextMenuComponent],
            template: `<app-explorer-context-menu
                [open]="menuOpen()"
                [position]="menuPosition()"
                [items]="menuItems()"
                (action)="onMenuItemAction($event)"
                (close)="closeMenu()"
            />`,
        },
    });
    const fixture = TestBed.createComponent(ExplorerComponent);
    const actions: ExplorerTreeMenuEvent[] = [];
    fixture.componentInstance.treeMenuAction.subscribe((event) => actions.push(event));
    fixture.detectChanges();
    return { fixture, host: fixture.nativeElement as HTMLElement, actions };
}

function menuItem(host: HTMLElement, label: string): HTMLButtonElement | null {
    return (
        Array.from(host.querySelectorAll<HTMLButtonElement>('.explorer-menu__item')).find(
            (item) => item.textContent?.trim() === label
        ) ?? null
    );
}

describe('ExplorerComponent row menu', () => {
    it('hands the chosen action on with the row and the ⋮ button that opened the menu, then closes', () => {
        const { fixture, host, actions } = render();
        const trigger = document.createElement('button');

        fixture.componentInstance.onTreeMenuOpen({
            node: AGENT_NODE,
            items: [
                {
                    id: 'view-details',
                    label: 'View Details',
                    resource: ResourceCode.Agents,
                    action: ActionCode.Read,
                },
            ],
            position: { x: 0, y: 0 },
            trigger,
        });
        fixture.detectChanges();
        menuItem(host, 'View Details')!.click();
        fixture.detectChanges();

        expect(actions).toEqual([{ node: AGENT_NODE, action: 'view-details', trigger }]);
        expect(menuItem(host, 'View Details')).toBeNull();
    });
});
