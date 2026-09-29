// AG Grid's own box for its scrollbar when the browser's take no room (INVISIBLE_SCROLLBAR_SIZE in ag-grid-community).
const OVERLAY_SCROLLBAR_ROOM_PX = 16;

/**
 * The `scrollbarWidth` an AG Grid needs to keep its vertical scrollbar off the cells; undefined to let it measure.
 *
 * Where the browser draws overlay scrollbars (Firefox on GTK, macOS), a scrollbar takes no room, so AG Grid measures
 * 0 and lays the columns out to the full width, then floats its scrollbar in a 16px box over the last column.
 * Telling it that box is the scrollbar's width makes it keep that room free. Classic scrollbars (their width is
 * measured) are left to the grid, which already reserves them.
 */
export function overlayScrollbarRoom(document: Document): number | undefined {
    const probe = document.createElement('div');
    probe.style.cssText = 'position: absolute; width: 100px; height: 100px; overflow: scroll; visibility: hidden';
    document.body.appendChild(probe);
    const scrollbarWidth = probe.offsetWidth - probe.clientWidth;
    // No layout (a zero box, as in jsdom): nothing is known about the scrollbars.
    const measured = probe.clientWidth > 0;
    probe.remove();
    return measured && scrollbarWidth === 0 ? OVERLAY_SCROLLBAR_ROOM_PX : undefined;
}
