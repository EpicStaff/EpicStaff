import { ConnectedPosition, Overlay, OverlayRef, PositionStrategy } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { DOCUMENT } from '@angular/common';
import { ComponentRef, inject, Injector, NgZone, runInInjectionContext } from '@angular/core';
import { Observable, Subject } from 'rxjs';

import { TourFloatingPosition, TourSide } from '../../model/tour-content';
import { TourIntent, TourRenderer, TourStepView } from '../tour-renderer';
import { isTourTargetVisible } from '../tour-target-visibility';
import { tourAnnouncement } from './tour-announcement';
import { TourFocusCycle } from './tour-focus-cycle';
import { TourPopoverComponent } from './tour-popover.component';
import { tourHolePadding, TourSpotlightComponent } from './tour-spotlight.component';
import { revealTourTarget, TourTargetGeometry } from './tour-target-geometry';

/** Space between the edge of the spotlight hole and the popover. */
const POPOVER_GAP = 12;
const VIEWPORT_MARGIN = 8;
/** A `bottom-start` popover's distance from the viewport's bottom-left corner. */
const FLOATING_INSET = '24px';

/** The two overlays of a running tour: the dimmed spotlight, and the popover above it. */
interface TourLayers {
    readonly spotlightOverlay: OverlayRef;
    readonly spotlight: ComponentRef<TourSpotlightComponent>;
    readonly popoverOverlay: OverlayRef;
    readonly popover: ComponentRef<TourPopoverComponent>;
}

type TourPlacement =
    | { readonly kind: 'anchored'; readonly target: Element; readonly side: TourSide }
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
        // Rendered now, so the overlay positions the card at its new size.
        layers.popover.changeDetectorRef.detectChanges();
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
        this.place(
            anchor
                ? { kind: 'anchored', target: anchor, side: view.side }
                : { kind: 'floating', position: view.floating }
        );
        this.focusCycle.setTarget(anchor);
        layers.spotlight.setInput('target', anchor);
        layers.spotlight.setInput('targetRect', rect);
        layers.spotlight.setInput('viewport', this.geometry.viewport());
        // Drawn in the same frame the popover moves in, not on the next application tick (this runs on scroll).
        layers.spotlight.changeDetectorRef.detectChanges();
    }

    private place(placement: TourPlacement): void {
        const overlayRef = this.layers?.popoverOverlay;
        if (!overlayRef) {
            return;
        }
        if (isSamePlacement(placement, this.placement)) {
            overlayRef.updatePosition();
            return;
        }
        this.placement = placement;
        overlayRef.updatePositionStrategy(
            placement.kind === 'anchored'
                ? this.anchoredStrategy(placement.target, placement.side)
                : this.floatingStrategy(placement.position)
        );
    }

    private anchoredStrategy(target: Element, side: TourSide): PositionStrategy {
        return this.overlay
            .position()
            .flexibleConnectedTo(target)
            .withPositions(positionsFor(side, tourHolePadding(target) + POPOVER_GAP))
            .withFlexibleDimensions(false)
            .withPush(true)
            .withViewportMargin(VIEWPORT_MARGIN);
    }

    private floatingStrategy(position: TourFloatingPosition): PositionStrategy {
        const strategy = this.overlay.position().global();
        return position === 'center'
            ? strategy.centerHorizontally().centerVertically()
            : strategy.left(FLOATING_INSET).bottom(FLOATING_INSET);
    }
}

/** The preferred side first, then the opposite one, then the two others. */
function positionsFor(side: TourSide, offset: number): ConnectedPosition[] {
    const above: ConnectedPosition = {
        originX: 'center',
        originY: 'top',
        overlayX: 'center',
        overlayY: 'bottom',
        offsetY: -offset,
    };
    const below: ConnectedPosition = {
        originX: 'center',
        originY: 'bottom',
        overlayX: 'center',
        overlayY: 'top',
        offsetY: offset,
    };
    const before: ConnectedPosition = {
        originX: 'start',
        originY: 'center',
        overlayX: 'end',
        overlayY: 'center',
        offsetX: -offset,
    };
    const after: ConnectedPosition = {
        originX: 'end',
        originY: 'center',
        overlayX: 'start',
        overlayY: 'center',
        offsetX: offset,
    };
    const order: Record<TourSide, ConnectedPosition[]> = {
        top: [above, below, after, before],
        bottom: [below, above, after, before],
        left: [before, after, below, above],
        right: [after, before, below, above],
    };
    return order[side];
}

function isSamePlacement(first: TourPlacement, second: TourPlacement | null): boolean {
    if (!second || first.kind !== second.kind) {
        return false;
    }
    if (first.kind === 'floating' && second.kind === 'floating') {
        return first.position === second.position;
    }
    return (
        first.kind === 'anchored' &&
        second.kind === 'anchored' &&
        first.target === second.target &&
        first.side === second.side
    );
}

function focusedElement(document: Document): HTMLElement | null {
    const focused = document.activeElement;
    return focused instanceof HTMLElement && focused !== document.body ? focused : null;
}
