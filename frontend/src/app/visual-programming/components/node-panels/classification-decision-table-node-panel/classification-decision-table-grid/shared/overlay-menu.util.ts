import { Overlay, OverlayRef, ScrollStrategy } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { TemplateRef, ViewContainerRef } from '@angular/core';
import { Subscription } from 'rxjs';

export interface OverlayMenuConfig {
    /**
     * Panel CSS class(es) applied to the overlay pane.
     * Defaults to no panelClass (none set).
     */
    panelClass?: string | string[];
    /**
     * Y offset (px) for the primary downward position.
     * Defaults to 4.
     */
    offsetY?: number;
    /**
     * Whether to add a second fallback position that flips the menu above the
     * anchor when there is insufficient space below.
     * Defaults to true (matching column-header-menu / params-group-header).
     * Set to false to match enable-filter-header's single-position behaviour.
     */
    withFlipFallback?: boolean;
    /**
     * When true, calls .withPush(false) on the position strategy so the overlay
     * is never pushed into the viewport.
     * Defaults to true (matching column-header-menu / params-group-header).
     * Set to false to match enable-filter-header (which omits withPush entirely,
     * keeping the CDK default of allowing push).
     */
    withPush?: boolean;
    /**
     * Custom scroll strategy factory.  When omitted the controller uses
     * overlay.scrollStrategies.close() — the strategy shared by all three
     * original components.
     */
    scrollStrategy?: () => ScrollStrategy;
    /**
     * Whether the panel gets CDK's transparent backdrop. Defaults to true, which is
     * what a menu over inert content wants.
     *
     * Set to false when the panel opens over content that stays interactive: the
     * transparent backdrop is invisible but still swallows pointer events across
     * the whole overlay container, so the first click on anything behind it only
     * closes the panel. Without one the controller closes on an outside pointer
     * event instead, and that click reaches its target.
     */
    hasBackdrop?: boolean;
    /**
     * Which horizontal edge of the anchor the panel lines up with. Defaults to
     * 'end'. Use 'start' when the anchor can be clipped on its right: an 'end'
     * alignment then lines the panel up with an edge the user cannot see.
     */
    alignX?: 'start' | 'end';
    /**
     * Gap kept between the panel and the viewport edge. CDK's flexible dimensions
     * shrink the panel to fit within it, so a non-zero value is what keeps a tall
     * panel's footer on screen. Defaults to 0.
     */
    viewportMargin?: number;
    /**
     * Elements an outside pointer event may come from without closing the panel,
     * on top of the anchor itself. Needed for a toggle button that owns its own
     * open/close: without it the panel closes on pointerdown and the click
     * handler can no longer tell whether it was open.
     */
    ignoreOutsideFor?: readonly HTMLElement[];
}

const DEFAULT_CONFIG: Required<Omit<OverlayMenuConfig, 'panelClass' | 'scrollStrategy' | 'ignoreOutsideFor'>> = {
    offsetY: 4,
    withFlipFallback: true,
    withPush: true,
    hasBackdrop: true,
    alignX: 'end',
    viewportMargin: 0,
};

/**
 * OverlayMenuController
 *
 * A small, composable helper that encapsulates the CDK Overlay dropdown-menu
 * pattern shared by the CDT header components.  Instantiate it once per
 * component (in the constructor or as a field) and delegate open/close/toggle
 * calls to it.  Call dispose() from ngOnDestroy.
 *
 * Usage:
 *   private menuCtrl = new OverlayMenuController(
 *     inject(Overlay),
 *     inject(ViewContainerRef),
 *   );
 */
export class OverlayMenuController {
    private overlayRef: OverlayRef | null = null;
    private backdropSub: Subscription | null = null;

    constructor(
        private readonly overlay: Overlay,
        private readonly vcr: ViewContainerRef
    ) {}

    /** Returns true when the menu panel is currently open. */
    isOpen(): boolean {
        return this.overlayRef?.hasAttached() ?? false;
    }

    /**
     * Toggle: closes if open, opens if closed.
     * Pass the anchor element (typically event.currentTarget).
     */
    toggle(anchor: HTMLElement, template: TemplateRef<unknown>, cfg?: OverlayMenuConfig): void {
        if (this.isOpen()) {
            this.close();
        } else {
            this.open(anchor, template, cfg);
        }
    }

    /** Open the menu anchored to the given element. No-ops if already open. */
    open(anchor: HTMLElement, template: TemplateRef<unknown>, cfg?: OverlayMenuConfig): void {
        if (this.isOpen()) {
            return;
        }

        const offsetY = cfg?.offsetY ?? DEFAULT_CONFIG.offsetY;
        const withFlip = cfg?.withFlipFallback ?? DEFAULT_CONFIG.withFlipFallback;
        // disablePush: when true, call .withPush(false) on the strategy.
        // Default is true to match column-header-menu / params-group-header.
        // enable-filter-header passes false to preserve its original omission of withPush.
        const disablePush = cfg?.withPush ?? DEFAULT_CONFIG.withPush;
        const alignX = cfg?.alignX ?? DEFAULT_CONFIG.alignX;
        const viewportMargin = cfg?.viewportMargin ?? DEFAULT_CONFIG.viewportMargin;

        let posBuilder = this.overlay
            .position()
            .flexibleConnectedTo(anchor)
            .withViewportMargin(viewportMargin)
            .withPositions([
                {
                    originX: alignX,
                    originY: 'bottom',
                    overlayX: alignX,
                    overlayY: 'top',
                    offsetY,
                },
                ...(withFlip
                    ? [
                          {
                              originX: alignX,
                              originY: 'top' as const,
                              overlayX: alignX,
                              overlayY: 'bottom' as const,
                              offsetY: -offsetY,
                          },
                      ]
                    : []),
            ]);

        if (disablePush) {
            posBuilder = posBuilder.withPush(false);
        }

        const scrollStrategy = cfg?.scrollStrategy ? cfg.scrollStrategy() : this.overlay.scrollStrategies.close();
        const hasBackdrop = cfg?.hasBackdrop ?? DEFAULT_CONFIG.hasBackdrop;

        this.overlayRef = this.overlay.create({
            positionStrategy: posBuilder,
            hasBackdrop,
            ...(hasBackdrop ? { backdropClass: 'cdk-overlay-transparent-backdrop' } : {}),
            scrollStrategy,
            ...(cfg?.panelClass ? { panelClass: cfg.panelClass } : {}),
        });

        this.backdropSub = hasBackdrop
            ? this.overlayRef.backdropClick().subscribe(() => this.close())
            : this.overlayRef.outsidePointerEvents().subscribe((event) => {
                  // The anchor and `ignoreOutsideFor` are excluded because callers
                  // open the panel from a click on them: closing here would fight
                  // the reopen and leave the panel flickering on its own trigger.
                  const target = event.target as Node | null;
                  if (target && anchor.contains(target)) return;
                  if (target && cfg?.ignoreOutsideFor?.some((element) => element.contains(target))) return;
                  this.close();
              });

        this.overlayRef.attach(new TemplatePortal(template, this.vcr));
    }

    /** Close and dispose the overlay panel. Safe to call when already closed. */
    close(): void {
        this.backdropSub?.unsubscribe();
        this.backdropSub = null;
        this.overlayRef?.detach();
        this.overlayRef?.dispose();
        this.overlayRef = null;
    }

    /**
     * Full cleanup — call from ngOnDestroy.
     * Currently identical to close() but kept as a separate entry-point so
     * callers read as self-documenting and future teardown logic (e.g. removing
     * global listeners) has a natural home.
     */
    dispose(): void {
        this.close();
    }
}
