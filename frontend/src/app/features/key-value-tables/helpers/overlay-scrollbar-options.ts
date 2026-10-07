import { GridOptions } from 'ag-grid-community';

// AG Grid's own box for its scrollbar when the browser's take no room (INVISIBLE_SCROLLBAR_SIZE in ag-grid-community).
const OVERLAY_SCROLLBAR_ROOM_PX = 16;

/**
 * The grid options that keep AG Grid's vertical scrollbar off the cells; empty to let the grid measure.
 *
 * Where the browser draws overlay scrollbars (Firefox on GTK, macOS), a scrollbar takes no room, so AG Grid floats
 * its own in a 16px box over the right edge of the rows. It sizes flex columns to leave that room only when the grid
 * viewport resizes, and a scrollbar that appears once rows load does not resize it, so the columns keep the full
 * width under the scrollbar. Both options are needed: `scrollbarWidth` is the room to leave, and
 * `alwaysShowVerticalScroll` counts the scrollbar from the first sizing, before any rows. With few rows the room
 * stays empty. Classic scrollbars (their width is measured) are left to the grid: the horizontal scrollbar they
 * bring up takes room, which resizes the viewport and re-sizes the columns.
 *
 * ponytail: works around AG Grid 36.1/36.2 not re-sizing flex columns when its vertical scrollbar shows or hides;
 * drop this once it does.
 */
export function overlayScrollbarOptions(
    document: Document
): Pick<GridOptions, 'scrollbarWidth' | 'alwaysShowVerticalScroll'> {
    const probe = document.createElement('div');
    probe.style.cssText = 'position: absolute; width: 100px; height: 100px; overflow: scroll; visibility: hidden';
    document.body.appendChild(probe);
    const scrollbarWidth = probe.offsetWidth - probe.clientWidth;
    // No layout (a zero box, as in jsdom): nothing is known about the scrollbars.
    const measured = probe.clientWidth > 0;
    probe.remove();
    return measured && scrollbarWidth === 0
        ? { scrollbarWidth: OVERLAY_SCROLLBAR_ROOM_PX, alwaysShowVerticalScroll: true }
        : {};
}
