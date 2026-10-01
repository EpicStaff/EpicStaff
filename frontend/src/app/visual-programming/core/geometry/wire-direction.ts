import { IPoint } from '@foblex/2d';

import { Rect } from '../routing/obstacles';

/**
 * The one classification of a left-to-right wire (port points, padded node boxes), shared by the
 * canvas (dashed + drawn under the others), the router and the quality checker:
 * - stacked: the nodes' boxes overlap in x, one sits above the other;
 * - backward: the target's input lies left of the source's output, except a stacked pair whose
 *   target sits below the source. That one is a sequential wire returning through the gap
 *   between them, drawn solid; a stacked pair wired bottom to top stays backward.
 * A backward wire that isn't stacked is a return wire: it goes over the top of both nodes.
 */
export function isStacked(sourceBox: Rect, targetBox: Rect): boolean {
    return sourceBox.left < targetBox.right && targetBox.left < sourceBox.right;
}

export function isBackwardWire(source: IPoint, target: IPoint, sourceBox: Rect, targetBox: Rect): boolean {
    if (target.x >= source.x) return false;
    return !(isStacked(sourceBox, targetBox) && targetBox.top > sourceBox.top);
}
