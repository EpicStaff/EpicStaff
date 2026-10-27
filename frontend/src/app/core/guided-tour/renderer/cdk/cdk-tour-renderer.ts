import {
    ConnectedPosition,
    FlexibleConnectedPositionStrategy,
    FlexibleConnectedPositionStrategyOrigin,
    Overlay,
    OverlayRef,
    PositionStrategy,
} from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { DOCUMENT } from '@angular/common';
import { ComponentRef, inject, Injector, NgZone, runInInjectionContext } from '@angular/core';
import { Observable, Subject } from 'rxjs';

import { TourFloatingPosition, TourSide } from '../../model/tour-content';
import { TourIntent, TourRenderer, TourStepView } from '../tour-renderer';
import { isTourTargetVisible } from '../tour-target-visibility';
import { tourAnnouncement } from './tour-announcement';
import { TourFocusCycle } from './tour-focus-cycle';
import { TourPopoverComponent, TourPopoverMaxSize } from './tour-popover.component';
import { tourHolePadding, TourSpotlightComponent } from './tour-spotlight.component';
import { revealTourTarget, TourRect, TourTargetGeometry, TourViewportSize } from './tour-target-geometry';

/** Space between the edge of the spotlight hole and the popover. */
const POPOVER_GAP = 12;
/** The least space between the popover and the edge of the viewport. */
const VIEWPORT_MARGIN = 8;
/**
 * A `bottom-start` popover's distance from the viewport's left edge: the width of the collapsed app navigation
 * (main-layout's MAIN_SIDENAV_COLLAPSED_WIDTH; core cannot depend on the layout), so the card sits just right of it,
 * where the Quick Start welcome card has always been. See TourFloatingPosition for where that falls short.
 */
const FLOATING_START_INSET = 60;
/** A `bottom-start` popover's distance from the viewport's bottom edge. */
const FLOATING_BOTTOM_INSET = 24;

/** The two overlays of a running tour: the dimmed spotlight, and the popover above it. */
interface TourLayers {
    readonly spotlightOverlay: OverlayRef;
    readonly spotlight: ComponentRef<TourSpotlightComponent>;
    readonly popoverOverlay: OverlayRef;
    readonly popover: ComponentRef<TourPopoverComponent>;
}

/** Where the popover is, with the strategy that keeps it there while anchored. */
type TourPlacement =
    | {
          readonly kind: 'anchored';
          readonly target: Element;
          readonly side: TourSide;
          readonly strategy: FlexibleConnectedPositionStrategy;
      }
    | { readonly kind: 'floating'; readonly position: TourFloatingPosition };

/** Creates a renderer that lives until its dispose(). `injector` provides the CDK services. */
export function createCdkTourRenderer(injector: Injector): TourRenderer {
    return runInInjectionContext(injector, () => new CdkTourRenderer());
}

/**
 * Renders a tour with CDK overlays: a full-viewport spotlight and a popover anchored to the target (or floating when
 * there is none). Both live in the browser top layer like every CDK overlay, so each step can raise them above
 * overlays opened since (e.g. a dropdown the step points into), without moving anyone else's DOM.
 */
class CdkTourRenderer implements TourRenderer {
    private readonly intentSubject = new Subject<TourIntent>();
    readonly intents: Observable<TourIntent> = this.intentSubject.asObservable();

    private readonly overlay = inject(Overlay);
    private readonly document = inject(DOCUMENT);
    private readonly ngZone = inject(NgZone);
    private readonly injector = inject(Injector);
    private readonly geometry = new TourTargetGeometry(() => this.followTarget());
    // Every Escape is reported; whether it ends the tour is the tour's decision (see TourIntent).
    private readonly focusCycle = new TourFocusCycle(() => this.intentSubject.next('escape'));
    private layers: TourLayers | null = null;
    private view: TourStepView | null = null;
    private placement: TourPlacement | null = null;
    /** Gets the focus back when the tour ends while the focus is in its popover. */
    private focusBeforeTour: HTMLElement | null = null;
    private isDisposed = false;

    show(view: TourStepView): void {
        if (this.isDisposed) {
            return;
        }
        // One zone turn for creating, filling and rendering: an application tick in between would render the
        // components before their required inputs are set.
        this.ngZone.run(() => this.showStep(view));
    }

    setPending(isPending: boolean): void {
        const layers = this.layers;
        if (this.isDisposed || !layers) {
            return;
        }
        layers.popover.setInput('pending', isPending);
        layers.popover.changeDetectorRef.detectChanges();
    }

    dispose(): void {
        if (this.isDisposed) {
            return;
        }
        this.isDisposed = true;
        const returnFocusTo = this.focusCycle.isFocusInPopover() ? this.focusBeforeTour : null;
        this.focusCycle.dispose();
        this.geometry.dispose();
        this.layers?.popoverOverlay.dispose();
        this.layers?.spotlightOverlay.dispose();
        this.layers = null;
        this.view = null;
        if (returnFocusTo?.isConnected) {
            returnFocusTo.focus({ preventScroll: true });
        }
        this.intentSubject.complete();
    }

    private showStep(view: TourStepView): void {
        const isFirstStep = this.view === null;
        if (isFirstStep) {
            this.focusBeforeTour = focusedElement(this.document);
        }
        const layers = this.ensureLayers();
        this.view = view;
        if (view.target && isTourTargetVisible(view.target)) {
            revealTourTarget(view.target);
        }
        // Followed even while hidden, so it is anchored once it shows (e.g. the window grows out of the phone layout).
        this.geometry.track(view.target);
        layers.popover.setInput('content', view.content);
        layers.popover.setInput('buttons', view.buttons);
        layers.popover.setInput('progress', view.progress);
        layers.popover.setInput('pending', false);
        this.followTarget();
        this.raise();
        this.focusCycle.presentStep(
            layers.popover.instance,
            tourAnnouncement(view.content, view.progress),
            isFirstStep
        );
    }

    /** Puts the tour above every overlay opened since its step started (e.g. a dropdown the step points into). */
    private raise(): void {
        const layers = this.layers;
        if (!layers) {
            return;
        }
        const focused = focusedElement(this.document);
        // The last-shown popover is on top: the spotlight first, then the card above it.
        for (const host of [layers.spotlightOverlay.hostElement, layers.popoverOverlay.hostElement]) {
            // Without the Popover API (old browsers, jsdom) CDK does not use the top layer, so there is nothing to win.
            if (!host.hasAttribute('popover') || typeof host.showPopover !== 'function') {
                continue;
            }
            if (host.matches(':popover-open')) {
                host.hidePopover();
            }
            host.showPopover();
        }
        // Hiding a popover moves the focus out of it.
        if (focused?.isConnected && focusedElement(this.document) !== focused) {
            focused.focus({ preventScroll: true });
        }
    }

    /**
     * Creates both layers, or none: when one fails, the overlays already created are disposed here, since dispose() only
     * reaches complete layers and a lone spotlight would leave the whole viewport dimmed.
     */
    private ensureLayers(): TourLayers {
        if (this.layers) {
            return this.layers;
        }
        const createdOverlays: OverlayRef[] = [];
        try {
            const spotlightOverlay = this.createOverlay(createdOverlays);
            const spotlight = spotlightOverlay.attach(new ComponentPortal(TourSpotlightComponent, null, this.injector));
            const popoverOverlay = this.createOverlay(createdOverlays);
            const popover = popoverOverlay.attach(new ComponentPortal(TourPopoverComponent, null, this.injector));
            popover.instance.intent.subscribe((intent) => this.intentSubject.next(intent));
            this.focusCycle.attach(popoverOverlay.overlayElement);
            this.layers = { spotlightOverlay, spotlight, popoverOverlay, popover };
            return this.layers;
        } catch (error: unknown) {
            createdOverlays.forEach((overlayRef) => overlayRef.dispose());
            throw error;
        }
    }

    /** A full-viewport overlay, added to `createdOverlays` as soon as it exists. */
    private createOverlay(createdOverlays: OverlayRef[]): OverlayRef {
        const overlayRef = this.overlay.create({ positionStrategy: this.overlay.position().global() });
        createdOverlays.push(overlayRef);
        return overlayRef;
    }

    /** Puts the popover and the spotlight hole where the target is now; floating while it is not visible. */
    private followTarget(): void {
        const layers = this.layers;
        const view = this.view;
        if (!layers || !view) {
            return;
        }
        const rect = this.geometry.rect();
        const anchor = rect ? view.target : null;
        const floating = anchor ? null : view.floating;
        layers.popover.setInput('maxSize', popoverMaxSize(floating, this.geometry.viewport()));
        // Rendered now, so the overlay positions the card at its new size; then again once the card knows whether its
        // content scrolls at that size (a Tab stop only then).
        layers.popover.changeDetectorRef.detectChanges();
        layers.popover.instance.updateContentScrolls();
        layers.popover.changeDetectorRef.detectChanges();
        if (anchor && rect) {
            this.anchor(anchor, view.side, rect);
        } else {
            this.float(view.floating);
        }
        this.focusCycle.setTarget(anchor);
        layers.spotlight.setInput('target', anchor);
        layers.spotlight.setInput('targetRect', rect);
        layers.spotlight.setInput('viewport', this.geometry.viewport());
        // Drawn in the same frame the popover moves in, not on the next application tick (this runs on scroll).
        layers.spotlight.changeDetectorRef.detectChanges();
    }

    /**
     * Places the popover next to the target's hole, measured by the geometry rather than by CDK, so the card and the
     * hole move together. The gap is part of the origin, not a position offset: CDK pushes an overlay back on screen
     * before it applies the offset, which would leave the card past the viewport's edge by up to the gap.
     */
    private anchor(target: Element, side: TourSide, rect: TourRect): void {
        const overlayRef = this.layers?.popoverOverlay;
        if (!overlayRef) {
            return;
        }
        const origin = popoverOrigin(target, rect);
        const placement = this.placement;
        if (placement?.kind === 'anchored' && placement.target === target && placement.side === side) {
            placement.strategy.setOrigin(origin);
            overlayRef.updatePosition();
            return;
        }
        const strategy = this.overlay
            .position()
            .flexibleConnectedTo(origin)
            .withPositions(positionsFor(side))
            .withFlexibleDimensions(false)
            .withPush(true)
            .withViewportMargin(VIEWPORT_MARGIN);
        this.placement = { kind: 'anchored', target, side, strategy };
        overlayRef.updatePositionStrategy(strategy);
    }

    private float(position: TourFloatingPosition): void {
        const overlayRef = this.layers?.popoverOverlay;
        if (!overlayRef) {
            return;
        }
        if (this.placement?.kind === 'floating' && this.placement.position === position) {
            overlayRef.updatePosition();
            return;
        }
        this.placement = { kind: 'floating', position };
        overlayRef.updatePositionStrategy(this.floatingStrategy(position));
    }

    private floatingStrategy(position: TourFloatingPosition): PositionStrategy {
        const strategy = this.overlay.position().global();
        return position === 'center'
            ? strategy.centerHorizontally().centerVertically()
            : strategy.left(`${FLOATING_START_INSET}px`).bottom(`${FLOATING_BOTTOM_INSET}px`);
    }
}

/** The target's hole (see tourHolePadding) grown by the gap: the box the popover is placed against. */
function popoverOrigin(target: Element, rect: TourRect): FlexibleConnectedPositionStrategyOrigin {
    const spacing = tourHolePadding(target) + POPOVER_GAP;
    return {
        x: rect.left - spacing,
        y: rect.top - spacing,
        width: rect.width + spacing * 2,
        height: rect.height + spacing * 2,
    };
}

/**
 * The most the card may take of the viewport where it is: anchored (null) or centred, all of it but the margins; at
 * `bottom-start`, what is left right of and above its insets. Past that its text scrolls.
 */
function popoverMaxSize(floating: TourFloatingPosition | null, viewport: TourViewportSize): TourPopoverMaxSize {
    const isBottomStart = floating === 'bottom-start';
    const horizontalSpace = isBottomStart ? FLOATING_START_INSET + VIEWPORT_MARGIN : VIEWPORT_MARGIN * 2;
    const verticalSpace = isBottomStart ? FLOATING_BOTTOM_INSET + VIEWPORT_MARGIN : VIEWPORT_MARGIN * 2;
    return {
        width: Math.max(viewport.width - horizontalSpace, 0),
        height: Math.max(viewport.height - verticalSpace, 0),
    };
}

/** The preferred side first, then the opposite one, then the two others. */
function positionsFor(side: TourSide): ConnectedPosition[] {
    const above: ConnectedPosition = { originX: 'center', originY: 'top', overlayX: 'center', overlayY: 'bottom' };
    const below: ConnectedPosition = { originX: 'center', originY: 'bottom', overlayX: 'center', overlayY: 'top' };
    const before: ConnectedPosition = { originX: 'start', originY: 'center', overlayX: 'end', overlayY: 'center' };
    const after: ConnectedPosition = { originX: 'end', originY: 'center', overlayX: 'start', overlayY: 'center' };
    const order: Record<TourSide, ConnectedPosition[]> = {
        top: [above, below, after, before],
        bottom: [below, above, after, before],
        left: [before, after, below, above],
        right: [after, before, below, above],
    };
    return order[side];
}

function focusedElement(document: Document): HTMLElement | null {
    const focused = document.activeElement;
    return focused instanceof HTMLElement && focused !== document.body ? focused : null;
}
