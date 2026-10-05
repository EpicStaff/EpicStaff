/**
 * Geometry for the detail window's code block, whose bottom edge stays a fixed gap
 * above the bottom of the window while the window scrolls.
 *
 * Pure: the detail component reads the sizes from the DOM and writes the results
 * back; nothing here touches an element.
 */

/** Sub-pixel layout leaves `scrollTop` a fraction short of its maximum. */
const SCROLL_END_TOLERANCE_PX = 1;

/**
 * The height that puts the block's bottom edge `bottomGap` above the bottom of the
 * window: the distance from the block's top to that line, in viewport coordinates,
 * so it already accounts for how far the window has scrolled. Never negative — a
 * block scrolled out of view above has no height to give.
 */
export function codeBlockHeight(sizes: {
    viewportTop: number;
    viewportHeight: number;
    blockTop: number;
    bottomGap: number;
}): number {
    return Math.max(0, sizes.viewportTop + sizes.viewportHeight - sizes.bottomGap - sizes.blockTop);
}

/**
 * Whether the window cannot scroll any further down: the point at which the code
 * block takes over the scrolling. A window with nothing to scroll counts as there.
 */
export function isScrolledToEnd(scroller: { scrollTop: number; scrollHeight: number; clientHeight: number }): boolean {
    return scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop <= SCROLL_END_TOLERANCE_PX;
}
