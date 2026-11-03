import { ViewportRuler } from '@angular/cdk/scrolling';
import { DOCUMENT } from '@angular/common';
import { inject, NgZone, signal } from '@angular/core';
import { Subscription } from 'rxjs';

import { isTourTargetVisible } from '../tour-target-visibility';

/**
 * Attributes that can move or hide an element without a scroll, resize or transition: CDK positioning a dropdown's pane
 * (`style` on the pane and its bounding box), a drawer opened by a class, `hidden` or `inert` taken off.
 */
const LAYOUT_ATTRIBUTES = ['style', 'class', 'hidden', 'inert'];
/** Document events after which the target may have moved: a scroll anywhere, the end of a CSS transition or animation. */
const MEASURE_EVENTS = ['scroll', 'transitionend', 'animationend'] as const;
/**
 * How long, once a step starts, the target is measured on every frame whatever happens on the page: it may still be
 * settling (CDK positions a dropdown after the next render, an image above the target loads).
 */
const SETTLE_MS = 500;

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
 * `cdkScrollable`, which `.main-content` and the settings content are not); on a resize of the target or of an ancestor
 * up to its first scroll container (content added or removed around the target resizes those while it moves it); on
 * viewport changes; when a CSS transition or animation ends (e.g. the phone drawer sliding in reveals its anchor); when a
 * layout attribute changes on the target or an ancestor (see LAYOUT_ATTRIBUTES); and on every frame for a short while
 * after a step starts. Listeners run outside the Angular zone and measuring is throttled to one per animation frame;
 * `onChange` runs only when something moved.
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
    private mutationObserver: MutationObserver | null = null;
    private viewportSubscription: Subscription | null = null;
    private frameRequest: number | null = null;
    /** Until when (performance.now() time) every frame is measured; 0 when not settling. */
    private settleUntil = 0;
    private isListening = false;

    private readonly measureOnFrame = (): void => {
        this.frameRequest = null;
        this.measure(true);
        if (performance.now() < this.settleUntil) {
            this.scheduleMeasure();
        }
    };

    private readonly scheduleMeasure = (): void => {
        if (this.frameRequest !== null) {
            return;
        }
        this.frameRequest = requestAnimationFrame(this.measureOnFrame);
    };

    constructor(private readonly onChange: () => void) {}

    /**
     * Follows `target` from now on (null: nothing to follow) and measures it at once, without calling onChange; then
     * on every frame for a short while.
     */
    track(target: Element | null): void {
        this.target = target;
        this.startListening();
        this.resizeObserver?.disconnect();
        this.mutationObserver?.disconnect();
        if (target) {
            this.observeTarget(target);
        }
        this.measure(false);
        this.settleUntil = target ? performance.now() + SETTLE_MS : 0;
        if (target) {
            this.ngZone.runOutsideAngular(this.scheduleMeasure);
        }
    }

    /** Idempotent. */
    dispose(): void {
        this.target = null;
        this.settleUntil = 0;
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
        this.mutationObserver?.disconnect();
        this.mutationObserver = null;
        this.viewportSubscription?.unsubscribe();
        this.viewportSubscription = null;
        for (const eventName of MEASURE_EVENTS) {
            this.document.removeEventListener(eventName, this.scheduleMeasure, { capture: true });
        }
    }

    private startListening(): void {
        if (this.isListening) {
            return;
        }
        this.isListening = true;
        this.ngZone.runOutsideAngular(() => {
            for (const eventName of MEASURE_EVENTS) {
                this.document.addEventListener(eventName, this.scheduleMeasure, { capture: true, passive: true });
            }
            // Not change(0): the ruler forgets its cached size only after its default delay, and a measure before that
            // would read the size from before the resize and miss it.
            this.viewportSubscription = this.viewportRuler.change().subscribe(this.scheduleMeasure);
            const view = this.document.defaultView;
            this.resizeObserver = view?.ResizeObserver ? new view.ResizeObserver(this.scheduleMeasure) : null;
            this.mutationObserver = view?.MutationObserver ? new view.MutationObserver(this.scheduleMeasure) : null;
        });
    }

    /**
     * Layout attributes on the target and every ancestor; sizes on the target and its ancestors up to and including the
     * first one that scrolls or clips. Each element on its own: changes elsewhere in the page are not watched.
     */
    private observeTarget(target: Element): void {
        let observesSize = true;
        for (let element: Element | null = target; element; element = element.parentElement) {
            this.mutationObserver?.observe(element, { attributes: true, attributeFilter: LAYOUT_ATTRIBUTES });
            if (observesSize) {
                this.resizeObserver?.observe(element);
                // Past a scroll container, a shift around the target no longer resizes anything.
                observesSize = element === target || !clipsOverflow(element);
            }
        }
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
        if (!clipsOverflow(ancestor)) {
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

/** Whether `element` scrolls or clips what overflows it, on either axis. */
function clipsOverflow(element: Element): boolean {
    const { overflowX, overflowY } = getComputedStyle(element);
    return overflowX !== 'visible' || overflowY !== 'visible';
}
