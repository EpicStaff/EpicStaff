/**
 * The attribute that marks an element a tour can point at. Templates bind it with `[attr.data-tour]="anchor"`; tour
 * steps name the anchor, never a CSS selector, so a template refactor cannot silently break a tour.
 */
export const TOUR_ANCHOR_ATTRIBUTE = 'data-tour';

/**
 * Selector for the element marked with `data-tour="<anchor>"`. Registered tours' anchors follow the tour key rule
 * (lowercase letters, digits and single hyphens; checked as the tours are registered), so they need no escaping.
 */
export function tourAnchorSelector(anchor: string): string {
    return `[${TOUR_ANCHOR_ATTRIBUTE}="${anchor}"]`;
}
