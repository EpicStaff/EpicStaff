import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GetGraphLightRequest } from '../../../features/flows/models/graph.model';
import { KeymapService } from '../../services/keymap.service';
import { FlowGraphContextMenuComponent } from './flow-graph-context-menu.component';

const VIEWPORT_WIDTH = 1024;
const VIEWPORT_HEIGHT = 768;
const MENU_WIDTH = 320;
const CURRENT_FLOW_ID = 1;
const CURRENT_FLOW = createFlow(CURRENT_FLOW_ID, 'Current flow');
const OTHER_FLOW = createFlow(2, 'Other flow');

function createFlow(id: number, name: string): GetGraphLightRequest {
    return { id, uuid: `uuid-${id}`, name, description: '' };
}

describe('FlowGraphContextMenuComponent', () => {
    let fixture: ComponentFixture<FlowGraphContextMenuComponent>;
    let overlayElement: HTMLElement;
    let contentHeight = 0;
    let viewportHeight = VIEWPORT_HEIGHT;
    let viewportWidth = VIEWPORT_WIDTH;

    afterEach(() => {
        vi.restoreAllMocks();
        viewportHeight = VIEWPORT_HEIGHT;
        viewportWidth = VIEWPORT_WIDTH;
    });

    async function openMenu(availableFlows: GetGraphLightRequest[], position = { x: 0, y: 0 }): Promise<void> {
        fixture = TestBed.createComponent(FlowGraphContextMenuComponent);
        fixture.componentRef.setInput('position', position);
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

    function fakeLayout(initialContentHeight: number): void {
        contentHeight = initialContentHeight;
        vi.spyOn(document.documentElement, 'clientWidth', 'get').mockImplementation(() => viewportWidth);
        vi.spyOn(document.documentElement, 'clientHeight', 'get').mockImplementation(() => viewportHeight);
        const realGetBoundingClientRect = Element.prototype.getBoundingClientRect;
        vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
            return this instanceof HTMLElement && this.classList.contains('cdk-overlay-pane')
                ? paneRect(this, contentHeight, { width: viewportWidth, height: viewportHeight })
                : realGetBoundingClientRect.call(this);
        });
    }

    async function typeInSearch(term: string): Promise<void> {
        const searchInput = overlayElement.querySelector<HTMLInputElement>('.search-container input');
        if (!searchInput) {
            throw new Error('search input is not rendered');
        }
        searchInput.value = term;
        searchInput.dispatchEvent(new Event('input'));
        await render();
    }

    async function resizeWindowTo(height: number, width = viewportWidth): Promise<void> {
        viewportHeight = height;
        viewportWidth = width;
        window.dispatchEvent(new Event('resize'));
        await new Promise((resolve) => setTimeout(resolve, 50));
        await render();
    }

    function menuLeftAndRight(): { left: number; right: number } {
        const pane = overlayElement.querySelector('.cdk-overlay-pane');
        if (!pane) {
            throw new Error('menu is not rendered');
        }
        const { left, right } = pane.getBoundingClientRect();
        return { left, right };
    }

    function menuRect(): { top: number; height: number } {
        const pane = overlayElement.querySelector('.cdk-overlay-pane');
        if (!pane) {
            throw new Error('menu is not rendered');
        }
        const { top, height } = pane.getBoundingClientRect();
        return { top, height };
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
        const event = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true });
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

    it('puts the caret in the search input when it opens', async () => {
        await openMenu([CURRENT_FLOW]);

        expect(document.activeElement).toBe(overlayElement.querySelector('.context-menu .search-container input'));
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

    it('closes only itself on Escape: the editor Escape shortcut does not run', async () => {
        await openMenu([CURRENT_FLOW]);
        const closedListener = vi.fn();
        fixture.componentInstance.closed.subscribe(closedListener);
        const editorEscape = vi.fn();
        TestBed.inject(KeymapService).register('editing.escape', editorEscape, { allowInEditable: true });

        pressEscapeInSearchInput();

        expect(closedListener).toHaveBeenCalledTimes(1);
        expect(editorEscape).not.toHaveBeenCalled();
    });

    it('opened above the cursor near the bottom edge, keeps its top edge while the search shrinks and regrows the list', async () => {
        fakeLayout(480);
        await openMenu([CURRENT_FLOW], { x: 100, y: VIEWPORT_HEIGHT - 200 });
        expect(menuRect()).toEqual({ top: 86, height: 480 });

        contentHeight = 120;
        await typeInSearch('table');
        expect(menuRect()).toEqual({ top: 86, height: 120 });

        contentHeight = 600;
        await typeInSearch('');
        expect(menuRect()).toEqual({ top: 86, height: 480 });
    });

    it('opened below the cursor, keeps its top edge while the search shrinks and regrows the list', async () => {
        fakeLayout(480);
        await openMenu([CURRENT_FLOW], { x: 100, y: 100 });
        expect(menuRect()).toEqual({ top: 102, height: 480 });

        contentHeight = 120;
        await typeInSearch('table');
        expect(menuRect()).toEqual({ top: 102, height: 120 });

        contentHeight = 600;
        await typeInSearch('');
        expect(menuRect()).toEqual({ top: 102, height: 480 });
    });

    it('keeps its opening top and height after a window resize while the list is filtered', async () => {
        fakeLayout(480);
        await openMenu([CURRENT_FLOW], { x: 100, y: VIEWPORT_HEIGHT - 200 });
        contentHeight = 150;
        await typeInSearch('table');

        await resizeWindowTo(VIEWPORT_HEIGHT);
        contentHeight = 600;
        await typeInSearch('');

        expect(menuRect()).toEqual({ top: 86, height: 480 });
    });

    it('fits a window shorter than the menu: pushed to the top margin, the list scrolls inside', async () => {
        viewportHeight = 500;
        fakeLayout(480);

        await openMenu([CURRENT_FLOW], { x: 100, y: 250 });

        expect(menuRect()).toEqual({ top: 16, height: 468 });
    });

    it('stays inside a narrowed window when opened near the right edge, and returns when it widens again', async () => {
        fakeLayout(480);
        await openMenu([CURRENT_FLOW], { x: VIEWPORT_WIDTH - 24, y: 100 });
        expect(menuLeftAndRight()).toEqual({ left: 670, right: 990 });

        await resizeWindowTo(VIEWPORT_HEIGHT, 800);
        expect(menuLeftAndRight()).toEqual({ left: 464, right: 784 });

        await resizeWindowTo(VIEWPORT_HEIGHT, VIEWPORT_WIDTH);
        expect(menuLeftAndRight()).toEqual({ left: 670, right: 990 });
    });
});

function paneRect(pane: HTMLElement, contentHeight: number, viewport: { width: number; height: number }): DOMRect {
    const host = pane.parentElement as HTMLElement;
    const maxHeight = parseFloat(pane.style.maxHeight);
    const height = Number.isNaN(maxHeight) ? contentHeight : Math.min(contentHeight, maxHeight);
    const offsetX = parseFloat(/translateX\((-?[\d.]+)px\)/.exec(pane.style.transform)?.[1] ?? '0');
    const offsetY = parseFloat(/translateY\((-?[\d.]+)px\)/.exec(pane.style.transform)?.[1] ?? '0');
    if (host.classList.contains('cdk-global-overlay-wrapper')) {
        return new DOMRect(
            parseFloat(pane.style.marginLeft) || 0,
            parseFloat(pane.style.marginTop) || 0,
            MENU_WIDTH,
            height
        );
    }
    let top: number;
    if (pane.style.bottom) {
        top = viewport.height - parseFloat(pane.style.bottom) - height;
    } else if (pane.style.top) {
        top = parseFloat(pane.style.top);
    } else if (host.style.top === 'auto') {
        top = viewport.height - parseFloat(host.style.bottom) - height;
    } else {
        top = parseFloat(host.style.top) || 0;
    }
    let left: number;
    if (pane.style.right) {
        left = viewport.width - parseFloat(pane.style.right) - MENU_WIDTH;
    } else if (pane.style.left) {
        left = parseFloat(pane.style.left);
    } else if (host.style.left === 'auto') {
        left = viewport.width - parseFloat(host.style.right) - MENU_WIDTH;
    } else {
        left = parseFloat(host.style.left) || 0;
    }
    return new DOMRect(left + offsetX, top + offsetY, MENU_WIDTH, height);
}
