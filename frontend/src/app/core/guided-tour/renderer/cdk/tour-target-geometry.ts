import { ViewportRuler } from '@angular/cdk/scrolling';
import { DOCUMENT } from '@angular/common';
import { inject, NgZone, signal } from '@angular/core';
import { Subscription } from 'rxjs';

import { isTourTargetVisible } from '../tour-target-visibility';

/** A target's box in viewport coordinates. */
export interface TourRect {
    readonly top: number;
    readonly left: number;
    readonly width: number;
    readonly height: number;
}

export interface TourViewportSize {
    readonly width: number;
    readonly height: number;
}

/**
 * Scrolls `target` to the middle of its scroll containers when the viewport or one of them cuts it off. A target in
 * full view stays where it is, so the page does not jump on every step.
 */
export function revealTourTarget(target: Element): void {
    if (isClipped(target)) {
        target.scrollIntoView({ block: 'center', inline: 'nearest' });
    }
}

/**
 * Follows a target's box while a step shows it, so the spotlight and the popover move with it.
 *
 * Re-measures on any scroll (capture phase on the document: CDK's ScrollDispatcher only hears containers marked
 * `cdkScrollable`, which `.main-content` and the settings content are not), on the target's resize, on viewport
 * changes, and when a CSS transition ends (e.g. the phone drawer sliding in reveals its anchor). Listeners run outside
 * the Angular zone and measuring is throttled to one per animation frame; `onChange` runs only when something moved.
 */
export class TourTargetGeometry {
    private readonly rectSignal = signal<TourRect | null>(null, { equal: isSameRect });
    private readonly viewportSignal = signal<TourViewportSize>({ width: 0, height: 0 }, { equal: isSameSize });
    /** Null while there is no target or it is not visible (see isTourTargetVisible). */
    readonly rect = this.rectSignal.asReadonly();
    readonly viewport = this.viewportSignal.asReadonly();

    private readonly document = inject(DOCUMENT);
    private readonly ngZone = inject(NgZone);
    private readonly viewportRuler = inject(ViewportRuler);
    private target: Element | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private viewportSubscription: Subscription | null = null;
    private frameRequest: number | null = null;
    private isListening = false;

    private readonly scheduleMeasure = (): void => {
        if (this.frameRequest !== null) {
            return;
        }
        this.frameRequest = requestAnimationFrame(() => {
            this.frameRequest = null;
            this.measure(true);
        });
    };

    constructor(private readonly onChange: () => void) {}

    /** Follows `target` from now on (null: nothing to follow) and measures it at once, without calling onChange. */
    track(target: Element | null): void {
        this.target = target;
        this.startListening();
        this.resizeObserver?.disconnect();
        if (target) {
            this.resizeObserver?.observe(target);
        }
        this.measure(false);
    }

    /** Idempotent. */
    dispose(): void {
        this.target = null;
        if (this.frameRequest !== null) {
            cancelAnimationFrame(this.frameRequest);
            this.frameRequest = null;
        }
        if (!this.isListening) {
            return;
        }
        this.isListening = false;
        this.resizeObserver?.disconnect();
        this.resizeObserver = null;
        this.viewportSubscription?.unsubscribe();
        this.viewportSubscription = null;
        this.document.removeEventListener('scroll', this.scheduleMeasure, { capture: true });
        this.document.removeEventListener('transitionend', this.scheduleMeasure, { capture: true });
    }

    private startListening(): void {
        if (this.isListening) {
            return;
        }
        this.isListening = true;
        this.ngZone.runOutsideAngular(() => {
            this.document.addEventListener('scroll', this.scheduleMeasure, { capture: true, passive: true });
            this.document.addEventListener('transitionend', this.scheduleMeasure, { capture: true, passive: true });
            this.viewportSubscription = this.viewportRuler.change(0).subscribe(this.scheduleMeasure);
            const ResizeObserverConstructor = this.document.defaultView?.ResizeObserver;
            this.resizeObserver = ResizeObserverConstructor
                ? new ResizeObserverConstructor(this.scheduleMeasure)
                : null;
        });
    }

    private measure(notify: boolean): void {
        const target = this.target;
        const rect = target && isTourTargetVisible(target) ? toTourRect(target.getBoundingClientRect()) : null;
        const { width, height } = this.viewportRuler.getViewportSize();
        const viewport = { width, height };
        if (isSameRect(rect, this.rect()) && isSameSize(viewport, this.viewport())) {
            return;
        }
        this.rectSignal.set(rect);
        this.viewportSignal.set(viewport);
        if (notify) {
            this.onChange();
        }
    }
}

function toTourRect({ top, left, width, height }: DOMRect): TourRect {
    return { top, left, width, height };
}

function isSameRect(first: TourRect | null, second: TourRect | null): boolean {
    if (!first || !second) {
        return first === second;
    }
    return (
        first.top === second.top &&
        first.left === second.left &&
        first.width === second.width &&
        first.height === second.height
    );
}

function isSameSize(first: TourViewportSize, second: TourViewportSize): boolean {
    return first.width === second.width && first.height === second.height;
}

/** Whether the viewport or a scrolling or clipping ancestor cuts off part of `target`. */
function isClipped(target: Element): boolean {
    const rect = target.getBoundingClientRect();
    const view = target.ownerDocument.defaultView;
    if (view && (rect.top < 0 || rect.left < 0 || rect.bottom > view.innerHeight || rect.right > view.innerWidth)) {
        return true;
    }
    for (let ancestor = target.parentElement; ancestor; ancestor = ancestor.parentElement) {
        const { overflowX, overflowY } = getComputedStyle(ancestor);
        if (overflowX === 'visible' && overflowY === 'visible') {
            continue;
        }
        const bounds = ancestor.getBoundingClientRect();
        if (
            rect.top < bounds.top ||
            rect.left < bounds.left ||
            rect.bottom > bounds.bottom ||
            rect.right > bounds.right
        ) {
            return true;
        }
    }
    return false;
}
