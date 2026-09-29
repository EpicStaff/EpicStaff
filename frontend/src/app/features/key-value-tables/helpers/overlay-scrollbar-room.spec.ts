import { overlayScrollbarRoom } from './overlay-scrollbar-room';

// jsdom has no layout: give every element the box a 100px scrolling probe would have with a scrollbar this wide.
function stubScrollbar(scrollbarWidth: number): void {
    const offsetWidth = vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100);
    const clientWidth = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(100 - scrollbarWidth);
    onTestFinished(() => {
        offsetWidth.mockRestore();
        clientWidth.mockRestore();
    });
}

describe('overlayScrollbarRoom', () => {
    it("reserves AG Grid's 16px scrollbar box where scrollbars overlay the content", () => {
        stubScrollbar(0);
        expect(overlayScrollbarRoom(document)).toBe(16);
    });

    it('leaves classic scrollbars, which take room, to the grid', () => {
        stubScrollbar(12);
        expect(overlayScrollbarRoom(document)).toBeUndefined();
    });

    it('knows nothing without layout', () => {
        expect(overlayScrollbarRoom(document)).toBeUndefined();
    });

    it('removes its probe', () => {
        const children = document.body.childElementCount;
        overlayScrollbarRoom(document);
        expect(document.body.childElementCount).toBe(children);
    });
});
