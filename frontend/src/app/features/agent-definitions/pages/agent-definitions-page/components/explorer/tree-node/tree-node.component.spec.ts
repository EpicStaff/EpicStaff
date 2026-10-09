import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { StorageDragService } from '../../../../../../files/services/storage-drag.service';
import { BranchTreeNode } from '../../../../../models/tree-node.model';
import { SurfaceDragService } from '../../../../../services/surface-drag.service';
import { ExplorerTreeMenuOpenEvent, TreeNodeComponent } from './tree-node.component';

const AGENT_NODE: BranchTreeNode = { kind: 'agent', agentId: 3, label: 'CV Processor', children: [] };

type PermissionCheck = (resource: ResourceCode, action: ActionCode) => boolean;

const FULL_ACCESS: PermissionCheck = () => true;
const READ_ONLY: PermissionCheck = (_resource, action) => action === ActionCode.Read;

function render(
    node: BranchTreeNode,
    can: PermissionCheck
): { fixture: ComponentFixture<TreeNodeComponent>; host: HTMLElement; opened: ExplorerTreeMenuOpenEvent[] } {
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can } },
            { provide: StorageDragService, useValue: { isDragging: signal(false) } },
            { provide: SurfaceDragService, useValue: { isDragging: signal(false) } },
        ],
    });
    // The overflow tooltip needs ResizeObserver, which jsdom lacks; it plays no part in the row menu.
    TestBed.overrideComponent(TreeNodeComponent, { remove: { imports: [TooltipOnOverflowDirective] } });
    const fixture = TestBed.createComponent(TreeNodeComponent);
    fixture.componentRef.setInput('node', node);
    const opened: ExplorerTreeMenuOpenEvent[] = [];
    fixture.componentInstance.menuOpen.subscribe((event) => opened.push(event));
    fixture.detectChanges();
    return { fixture, host: fixture.nativeElement as HTMLElement, opened };
}

function moreButton(host: HTMLElement): HTMLButtonElement | null {
    return host.querySelector<HTMLButtonElement>('.row__hover-btn');
}

/** Clicks the row's ⋮ and returns the labels of the menu it asks the explorer to open. */
function openMenuLabels(host: HTMLElement, opened: ExplorerTreeMenuOpenEvent[]): string[] {
    moreButton(host)!.click();
    return opened[opened.length - 1].items.map((item) => item.label);
}

describe('TreeNodeComponent row menu "View Details"', () => {
    it('sits between Duplicate and Delete on an agent row', () => {
        const { host, opened } = render(AGENT_NODE, FULL_ACCESS);

        expect(openMenuLabels(host, opened)).toEqual(['Duplicate', 'View Details', 'Delete']);
    });

    it('is offered to a user who can only read agents, as the only item', () => {
        const { host, opened } = render(AGENT_NODE, READ_ONLY);

        expect(moreButton(host)).not.toBeNull();
        expect(openMenuLabels(host, opened)).toEqual(['View Details']);
    });

    it('opens the menu for that agent with the ⋮ button as the trigger', () => {
        const { host, opened } = render(AGENT_NODE, FULL_ACCESS);

        moreButton(host)!.click();

        expect(opened).toHaveLength(1);
        expect(opened[0].node).toBe(AGENT_NODE);
        expect(opened[0].trigger).toBe(moreButton(host));
    });

    it.each<[string, BranchTreeNode]>([
        ['a shared surface', { kind: 'surface', surfaceId: 5, label: 'Surface_1', shared: true }],
        [
            'a locked agent surface',
            { kind: 'surface', surfaceId: 5, label: 'Surface_1', ownerAgentId: 3, locked: true },
        ],
        [
            'a shared surface attached to an agent',
            { kind: 'surface', surfaceId: 5, label: 'Surface_1', ownerAgentId: 3 },
        ],
    ])('is not offered on %s row', (_description, node) => {
        const { host, opened } = render(node, FULL_ACCESS);

        expect(openMenuLabels(host, opened)).not.toContain('View Details');
    });

    it.each<[string, BranchTreeNode]>([
        ['a group', { kind: 'group', id: 'agent:3:surfaces', label: 'Surfaces', children: [] }],
        ['an agent document', { kind: 'agent-doc', agentId: 3, instructionIndex: 0, label: 'Boot' }],
    ])('leaves %s row without a menu', (_description, node) => {
        const { host } = render(node, FULL_ACCESS);

        expect(moreButton(host)).toBeNull();
    });
});
