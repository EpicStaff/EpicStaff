import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { StorageDragService } from '../../../../../../files/services/storage-drag.service';
import { BranchTreeNode } from '../../../../../models/tree-node.model';
import { AgentsPageStore } from '../../../../../services/agents-page-store.service';
import { SurfaceDragService } from '../../../../../services/surface-drag.service';
import { ExplorerTreeMenuOpenEvent, TreeNodeComponent } from './tree-node.component';

const AGENT_NODE: BranchTreeNode = { kind: 'agent', agentId: 3, label: 'CV Processor', children: [] };

type PermissionCheck = (resource: ResourceCode, action: ActionCode) => boolean;

const FULL_ACCESS: PermissionCheck = () => true;
const READ_ONLY: PermissionCheck = (_resource, action) => action === ActionCode.Read;

interface ExportSelectionStore {
    agentExportMode: WritableSignal<boolean>;
    selectedAgentIds: WritableSignal<Set<number>>;
    toggleAgentSelection(id: number): void;
}

/** The store's export selection, toggling like the real one. */
function exportSelectionStore(exportMode = false): ExportSelectionStore {
    const selectedAgentIds = signal(new Set<number>());
    return {
        agentExportMode: signal(exportMode),
        selectedAgentIds,
        toggleAgentSelection: (id) =>
            selectedAgentIds.update((ids) => {
                const next = new Set(ids);
                if (next.has(id)) next.delete(id);
                else next.add(id);
                return next;
            }),
    };
}

function render(
    node: BranchTreeNode,
    can: PermissionCheck,
    store: ExportSelectionStore = exportSelectionStore()
): { fixture: ComponentFixture<TreeNodeComponent>; host: HTMLElement; opened: ExplorerTreeMenuOpenEvent[] } {
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can } },
            { provide: StorageDragService, useValue: { isDragging: signal(false) } },
            { provide: SurfaceDragService, useValue: { isDragging: signal(false) } },
            { provide: AgentsPageStore, useValue: store },
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
    it('sits between Duplicate and Export on an agent row', () => {
        const { host, opened } = render(AGENT_NODE, FULL_ACCESS);

        expect(openMenuLabels(host, opened)).toEqual(['Duplicate', 'View Details', 'Export', 'Delete']);
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

describe('TreeNodeComponent row name', () => {
    const AGENT_WITH_DOC: BranchTreeNode = {
        kind: 'agent',
        agentId: 3,
        label: 'CV Processor',
        children: [{ kind: 'agent-doc', agentId: 3, instructionIndex: 0, label: 'Boot' }],
    };

    function nameButton(host: HTMLElement): HTMLButtonElement {
        return host.querySelector<HTMLButtonElement>('.row__name')!;
    }

    function pressOnName(host: HTMLElement, key: string): void {
        nameButton(host).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
    }

    it('is the keyboard stop of the row: a button with the label, while the row itself is not a button', () => {
        const { host } = render(AGENT_NODE, FULL_ACCESS);
        const row = host.querySelector<HTMLElement>('.row')!;

        expect(nameButton(host).type).toBe('button');
        expect(nameButton(host).textContent.trim()).toBe('CV Processor');
        expect(row.getAttribute('role')).toBeNull();
        expect(row.hasAttribute('tabindex')).toBe(false);
    });

    it('selects the node when the name is activated', () => {
        const { fixture, host } = render(AGENT_NODE, FULL_ACCESS);
        const selected: BranchTreeNode[] = [];
        fixture.componentInstance.selectNode.subscribe((node) => selected.push(node));

        nameButton(host).click();

        expect(selected).toEqual([AGENT_NODE]);
    });

    it('selects the node on a click anywhere on the row', () => {
        const { fixture, host } = render(AGENT_NODE, FULL_ACCESS);
        const selected: BranchTreeNode[] = [];
        fixture.componentInstance.selectNode.subscribe((node) => selected.push(node));

        host.querySelector<HTMLElement>('.row__icon')!.click();

        expect(selected).toEqual([AGENT_NODE]);
    });

    it('expands the children with ArrowRight on the name and collapses them with ArrowLeft', () => {
        const { fixture, host } = render(AGENT_WITH_DOC, FULL_ACCESS);

        pressOnName(host, 'ArrowRight');
        fixture.detectChanges();
        expect(host.querySelector('.children')).not.toBeNull();

        pressOnName(host, 'ArrowLeft');
        fixture.detectChanges();
        expect(host.querySelector('.children')).toBeNull();
    });
});

describe('TreeNodeComponent agent export selection', () => {
    function checkbox(host: HTMLElement): HTMLInputElement | null {
        return host.querySelector<HTMLInputElement>('.row__check input[type="checkbox"]');
    }

    it('shows no checkbox outside export mode', () => {
        const { host } = render(AGENT_NODE, FULL_ACCESS);

        expect(checkbox(host)).toBeNull();
    });

    it('shows an unticked checkbox on an agent row in export mode', () => {
        const { host } = render(AGENT_NODE, FULL_ACCESS, exportSelectionStore(true));

        expect(checkbox(host)).not.toBeNull();
        expect(checkbox(host)!.checked).toBe(false);
    });

    it('shows no checkbox on a surface row in export mode', () => {
        const { host } = render(
            { kind: 'surface', surfaceId: 5, label: 'Surface_1', shared: true },
            FULL_ACCESS,
            exportSelectionStore(true)
        );

        expect(checkbox(host)).toBeNull();
    });

    it('ticks the agent once when its checkbox is clicked', () => {
        const store = exportSelectionStore(true);
        const { fixture, host } = render(AGENT_NODE, FULL_ACCESS, store);

        checkbox(host)!.click();
        fixture.detectChanges();

        expect([...store.selectedAgentIds()]).toEqual([3]);
        expect(checkbox(host)!.checked).toBe(true);
    });

    it('ticks the agent instead of selecting it on a click anywhere on the row', () => {
        const store = exportSelectionStore(true);
        const { fixture, host } = render(AGENT_NODE, FULL_ACCESS, store);
        const selected: BranchTreeNode[] = [];
        fixture.componentInstance.selectNode.subscribe((node) => selected.push(node));

        host.querySelector<HTMLElement>('.row__icon')!.click();

        expect([...store.selectedAgentIds()]).toEqual([3]);
        expect(selected).toEqual([]);
    });

    it('unticks an agent that is already ticked', () => {
        const store = exportSelectionStore(true);
        store.selectedAgentIds.set(new Set([3]));
        const { host } = render(AGENT_NODE, FULL_ACCESS, store);

        host.querySelector<HTMLElement>('.row__icon')!.click();

        expect(store.selectedAgentIds().size).toBe(0);
    });

    it('stops the agent row from being dragged while in export mode', () => {
        const store = exportSelectionStore();
        const { fixture, host } = render(AGENT_NODE, FULL_ACCESS, store);
        const row = (): HTMLElement => host.querySelector<HTMLElement>('.row--agent')!;
        expect(row().getAttribute('draggable')).toBe('true');

        store.agentExportMode.set(true);
        fixture.detectChanges();

        expect(row().hasAttribute('draggable')).toBe(false);
    });
});
