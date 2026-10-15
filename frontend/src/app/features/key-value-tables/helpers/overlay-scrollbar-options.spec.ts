import { overlayScrollbarOptions } from './overlay-scrollbar-options';

// jsdom has no layout: give every element the box a 100px scrolling probe would have with a scrollbar this wide.
function stubScrollbar(scrollbarWidth: number): void {
    const offsetWidth = vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100);
    const clientWidth = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(100 - scrollbarWidth);
    onTestFinished(() => {
        offsetWidth.mockRestore();
        clientWidth.mockRestore();
    });
}

describe('overlayScrollbarOptions', () => {
    it("reserves AG Grid's 16px scrollbar box, rows or not, where scrollbars overlay the content", () => {
        stubScrollbar(0);
        expect(overlayScrollbarOptions(document)).toEqual({ scrollbarWidth: 16, alwaysShowVerticalScroll: true });
    });

    it('leaves classic scrollbars, which take room, to the grid', () => {
        stubScrollbar(12);
        expect(overlayScrollbarOptions(document)).toEqual({});
    });

    it('knows nothing without layout', () => {
        expect(overlayScrollbarOptions(document)).toEqual({});
    });

    it('removes its probe', () => {
        const children = document.body.childElementCount;
        overlayScrollbarOptions(document);
        expect(document.body.childElementCount).toBe(children);
    });
});
