/**
 * Parts of a header cell a click on which is not a click on the header: the cell's own
 * buttons handle their clicks themselves, the drag grip and the resize handle are for
 * dragging.
 */
const NOT_THE_HEADER = 'button, .drag-grip-btn, .ag-header-cell-resize';

/**
 * How far the pointer travels, on either axis, before ag-grid takes a press on a header
 * for a drag (its default `dragStartPixels`).
 */
const DRAG_START_PIXELS = 4;

/**
 * A click anywhere else on a header cell runs `activate`, which must do what a click on
 * the header's menu button does — the button is too small a target to be the only one.
 *
 * The click that ends a drag is not one. ag-grid moves a column once the pointer has
 * travelled past `DRAG_START_PIXELS`, and resizes it from the first pixel; the browser
 * still fires a click when the press ends over the header it began on, as when a column
 * is dragged away and back. So a press the pointer travelled that far in is no click.
 * Measured here, as the pointer moves: ag-grid tells its API listeners about a drag only
 * on a later task, which can come after the click.
 *
 * Nor is a press that began on one of the `NOT_THE_HEADER` parts: released a few pixels
 * away over the label, the browser fires the click on the element both share, which is
 * the header itself.
 *
 * Returns the function that stops listening.
 */
export function listenForHeaderClick(eGridHeader: HTMLElement, activate: () => void): () => void {
    const ownerDocument = eGridHeader.ownerDocument;
    let press: { x: number; y: number; dragged: boolean; startedOnPart: boolean } | null = null;
    const isOnPart = (target: EventTarget | null): boolean => {
        const part = target instanceof Element ? target.closest(NOT_THE_HEADER) : null;
        return part !== null && eGridHeader.contains(part);
    };

    const onPointerMove = (event: PointerEvent): void => {
        if (!press) return;
        const travel = Math.max(Math.abs(event.clientX - press.x), Math.abs(event.clientY - press.y));
        if (travel > DRAG_START_PIXELS) press.dragged = true;
    };
    // The press is followed over the whole document: a drag takes the pointer off the header.
    const stopFollowingPress = (): void => {
        ownerDocument.removeEventListener('pointermove', onPointerMove, true);
        ownerDocument.removeEventListener('pointerup', stopFollowingPress, true);
        ownerDocument.removeEventListener('pointercancel', stopFollowingPress, true);
    };
    const onPointerDown = (event: PointerEvent): void => {
        press = { x: event.clientX, y: event.clientY, dragged: false, startedOnPart: isOnPart(event.target) };
        ownerDocument.addEventListener('pointermove', onPointerMove, true);
        ownerDocument.addEventListener('pointerup', stopFollowingPress, true);
        ownerDocument.addEventListener('pointercancel', stopFollowingPress, true);
    };
    const onClick = (event: MouseEvent): void => {
        const dragged = press?.dragged ?? false;
        const startedOnPart = press?.startedOnPart ?? false;
        press = null;
        if (dragged || startedOnPart || isOnPart(event.target)) return;
        activate();
    };

    // Captured, so ag-grid's own handlers inside the cell cannot keep the press from being seen.
    eGridHeader.addEventListener('pointerdown', onPointerDown, true);
    eGridHeader.addEventListener('click', onClick);
    return () => {
        stopFollowingPress();
        eGridHeader.removeEventListener('pointerdown', onPointerDown, true);
        eGridHeader.removeEventListener('click', onClick);
    };
}
