/**
 * Whether the user can see and reach `target`: in the document, not hidden (`visibility` included, e.g. the phone
 * drawer slid out), not inert (e.g. the page behind an open drawer) and with a box. The one rule both the tour (which
 * content a step shows) and a renderer (whether to anchor and highlight) go by.
 */
export function isTourTargetVisible(target: Element): boolean {
    if (!target.isConnected || target.closest('[inert]')) {
        return false;
    }
    // Missing in old browsers (and jsdom); the box check below still catches display: none.
    if (typeof target.checkVisibility === 'function' && !target.checkVisibility({ visibilityProperty: true })) {
        return false;
    }
    const rect = target.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}
