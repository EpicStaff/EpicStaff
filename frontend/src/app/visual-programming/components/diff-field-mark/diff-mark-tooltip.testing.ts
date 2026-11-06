import { vi } from 'vitest';

/**
 * Lays out a 1024x768 window with `row` `top` px below its top and every overlay pane (a tooltip) 200x40, so a diff
 * tooltip picks its side as in a browser: above the row when there is room, below it otherwise. jsdom lays nothing
 * out (every size is 0), so without this every side "fits". Undo with `vi.restoreAllMocks()`.
 */
export function layOutWindowWithRowAt(row: HTMLElement, top: number): void {
    const rowRect = { top, bottom: top + 30, left: 100, right: 400, width: 300, height: 30, x: 100, y: top };
    const paneRect = { top: 0, bottom: 40, left: 0, right: 200, width: 200, height: 40, x: 0, y: 0 };
    const getBoundingClientRect = Element.prototype.getBoundingClientRect;
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
        if (this === row) return { ...rowRect, toJSON: () => rowRect } as DOMRect;
        if (this.classList.contains('cdk-overlay-pane')) return { ...paneRect, toJSON: () => paneRect } as DOMRect;
        return getBoundingClientRect.call(this);
    });
    vi.spyOn(document.documentElement, 'clientWidth', 'get').mockReturnValue(1024);
    vi.spyOn(document.documentElement, 'clientHeight', 'get').mockReturnValue(768);
}
