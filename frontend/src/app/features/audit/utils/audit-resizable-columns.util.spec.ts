import { AuditResizableColumns } from './audit-resizable-columns.util';

// A header cell 120px wide on screen with a resize handle inside it, wired to drag column 0.
function headerHandle(columns: AuditResizableColumns): HTMLElement {
    const headerCell = document.createElement('th');
    const handle = document.createElement('span');
    headerCell.append(handle);
    // the test DOM has no layout or pointer capture
    vi.spyOn(headerCell, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 120, 30));
    handle.setPointerCapture = () => undefined;
    handle.addEventListener('pointerdown', (event) => columns.start(event as PointerEvent, 0));
    handle.addEventListener('pointermove', (event) => columns.move(event as PointerEvent));
    return handle;
}

function drag(handle: HTMLElement, fromX: number, toX: number, button = 0): void {
    handle.dispatchEvent(new MouseEvent('pointerdown', { button, clientX: fromX }));
    handle.dispatchEvent(new MouseEvent('pointermove', { clientX: toX }));
}

describe('AuditResizableColumns', () => {
    it('makes the table as wide as its columns, before and after a resize', () => {
        const columns = new AuditResizableColumns([120, 200, 50]);
        expect(columns.tableWidth()).toBe(370);

        drag(headerHandle(columns), 100, 130);

        expect(columns.widths()).toEqual([150, 200, 50]);
        expect(columns.tableWidth()).toBe(400);
    });

    it.each([
        [-71, 49],
        [-72, 48],
        [-73, 48],
        [-500, 48],
    ])('dragged by %ipx a 120px column becomes %ipx, never narrower than the minimum', (distance, expected) => {
        const columns = new AuditResizableColumns([120, 200]);

        drag(headerHandle(columns), 300, 300 + distance);

        expect(columns.widths()).toEqual([expected, 200]);
    });

    it('honours a custom minimum width', () => {
        const columns = new AuditResizableColumns([120, 200], 80);

        drag(headerHandle(columns), 300, 0);

        expect(columns.widths()).toEqual([80, 200]);
    });

    it.each([1, 2])('ignores a drag started with mouse button %i', (button) => {
        const columns = new AuditResizableColumns([120, 200]);

        drag(headerHandle(columns), 100, 160, button);

        expect(columns.widths()).toEqual([120, 200]);
    });

    it('stops resizing once the drag ends', () => {
        const columns = new AuditResizableColumns([120, 200]);
        const handle = headerHandle(columns);
        drag(handle, 100, 110);

        columns.stop();
        handle.dispatchEvent(new MouseEvent('pointermove', { clientX: 300 }));

        expect(columns.widths()).toEqual([130, 200]);
    });
});
