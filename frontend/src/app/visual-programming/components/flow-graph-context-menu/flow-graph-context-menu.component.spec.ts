import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GetGraphLightRequest } from '../../../features/flows/models/graph.model';
import { FlowGraphContextMenuComponent } from './flow-graph-context-menu.component';

const CURRENT_FLOW_ID = 1;
const CURRENT_FLOW = createFlow(CURRENT_FLOW_ID, 'Current flow');
const OTHER_FLOW = createFlow(2, 'Other flow');

function createFlow(id: number, name: string): GetGraphLightRequest {
    return { id, uuid: `uuid-${id}`, name, description: '' };
}

describe('FlowGraphContextMenuComponent', () => {
    let fixture: ComponentFixture<FlowGraphContextMenuComponent>;
    let overlayElement: HTMLElement;

    async function openMenu(availableFlows: GetGraphLightRequest[]): Promise<void> {
        fixture = TestBed.createComponent(FlowGraphContextMenuComponent);
        fixture.componentRef.setInput('position', { x: 0, y: 0 });
        fixture.componentRef.setInput('currentFlowId', CURRENT_FLOW_ID);
        fixture.componentRef.setInput('availableFlows', availableFlows);
        overlayElement = TestBed.inject(OverlayContainer).getContainerElement();
        await render();
    }

    async function render(): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function menuHeader(): HTMLElement | null {
        return overlayElement.querySelector('.menu-header');
    }

    function coreMenu(): HTMLElement | null {
        return overlayElement.querySelector('app-flow-graph-core-menu');
    }

    function pressEscapeInSearchInput(): KeyboardEvent {
        const searchInput = overlayElement.querySelector<HTMLInputElement>('.search-container input');
        if (!searchInput) {
            throw new Error('search input is not rendered');
        }
        searchInput.focus();
        const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
        searchInput.dispatchEvent(event);
        return event;
    }

    it('hides the tab row and shows the Core menu when the only flow is the one being edited', async () => {
        await openMenu([CURRENT_FLOW]);

        expect(menuHeader()).toBeNull();
        expect(coreMenu()).not.toBeNull();
    });

    it('hides the tab row when there are no flows at all', async () => {
        await openMenu([]);

        expect(menuHeader()).toBeNull();
        expect(coreMenu()).not.toBeNull();
    });

    it('shows Core and Flows tabs when another flow exists, and lists only the other flow', async () => {
        await openMenu([CURRENT_FLOW, OTHER_FLOW]);

        const tabButtons = Array.from(menuHeader()?.querySelectorAll('button') ?? []);
        expect(tabButtons.map((button) => button.textContent?.trim())).toEqual(['Core', 'Flows']);

        tabButtons[1].click();
        await render();

        const flowsMenu = overlayElement.querySelector('app-flows-menu');
        expect(flowsMenu).not.toBeNull();
        const flowNames = Array.from(flowsMenu?.querySelectorAll('.flow-name') ?? []).map((element) =>
            element.textContent?.trim()
        );
        expect(flowNames).toEqual([OTHER_FLOW.name]);
    });

    it('shows the tab row when another flow arrives while the menu is open', async () => {
        await openMenu([CURRENT_FLOW]);
        expect(menuHeader()).toBeNull();

        fixture.componentRef.setInput('availableFlows', [CURRENT_FLOW, OTHER_FLOW]);
        await render();

        expect(menuHeader()).not.toBeNull();
    });

    it('emits closed once when Escape is pressed while the search input has focus', async () => {
        await openMenu([CURRENT_FLOW]);
        const closedListener = vi.fn();
        fixture.componentInstance.closed.subscribe(closedListener);

        pressEscapeInSearchInput();

        expect(closedListener).toHaveBeenCalledTimes(1);
    });

    it('keeps the Escape that closes the menu from reaching window-level shortcut listeners', async () => {
        await openMenu([CURRENT_FLOW]);
        const windowListener = vi.fn();
        window.addEventListener('keydown', windowListener);

        try {
            pressEscapeInSearchInput();
        } finally {
            window.removeEventListener('keydown', windowListener);
        }

        expect(windowListener).not.toHaveBeenCalled();
    });
});
