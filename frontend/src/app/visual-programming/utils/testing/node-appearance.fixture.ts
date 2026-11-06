/** A colour and icon that match no node type: what a stale saved node could still carry. */
export const WRONG_APPEARANCE = { color: '#ff0000', icon: 'ti ti-bug' };

/** The colour as the browser normalises it, so a hex constant compares equal to an inline style value. */
export function normalizedCssColor(color: string): string {
    const element = document.createElement('i');
    element.style.color = color;
    return element.style.color;
}
