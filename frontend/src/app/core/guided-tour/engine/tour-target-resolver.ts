import { fromEvent, map, Observable, of, race, timer } from 'rxjs';
import { filter } from 'rxjs/operators';

import { TOUR_ANCHOR_ATTRIBUTE, tourAnchorSelector } from '../model/tour-anchor';
import { TourClickTiming, TourTarget } from '../model/tour-definition';

/**
 * Emits the element marked with `anchor` once it is in the document (now, or after a DOM change), then completes.
 * Event-driven, not polling, and with no timeout of its own.
 */
export function anchorAppears(document: Document, anchor: string): Observable<Element> {
    const selector = tourAnchorSelector(anchor);
    return new Observable<Element>((subscriber) => {
        const found = document.querySelector(selector);
        if (found) {
            subscriber.next(found);
            subscriber.complete();
            return undefined;
        }
        const observer = new MutationObserver(() => {
            const element = document.querySelector(selector);
            if (element) {
                observer.disconnect();
                subscriber.next(element);
                subscriber.complete();
            }
        });
        // Attributes too: a template may bind the anchor onto an element that is already there.
        observer.observe(document.documentElement, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: [TOUR_ANCHOR_ATTRIBUTE],
        });
        return () => observer.disconnect();
    });
}

/** The step's target element: at once, or as soon as it appears within `waitMs`. Null when it does not turn up. */
export function resolveTourTarget(document: Document, target: TourTarget | undefined): Observable<Element | null> {
    if (!target) {
        return of(null);
    }
    const waitMs = target.waitMs ?? 0;
    if (waitMs <= 0) {
        return of(document.querySelector(tourAnchorSelector(target.anchor)));
    }
    return race(anchorAppears(document, target.anchor), timer(waitMs).pipe(map(() => null)));
}

/**
 * Clicks on or inside an element marked with `anchor`, at the given timing (see TourClickTiming). Matched by the
 * anchor, not by the element found when the step showed, so a re-render that replaced the element is still followed.
 * Both listen on the document: `after-target` in the bubble phase, so the clicked element and all its ancestors have
 * handled the click; `before-target` in the capture phase, before any of them. Neither stops the click.
 */
export function anchorClicks(document: Document, anchor: string, timing: TourClickTiming): Observable<void> {
    const selector = tourAnchorSelector(anchor);
    return fromEvent(document, 'click', { capture: timing === 'before-target' }).pipe(
        filter((event) => event.target instanceof Element && event.target.closest(selector) !== null),
        map(() => undefined)
    );
}
