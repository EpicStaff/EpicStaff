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
}

const DEFAULT_CONFIG: Required<Omit<OverlayMenuConfig, 'panelClass' | 'scrollStrategy'>> = {
    offsetY: 4,
    withFlipFallback: true,
    withPush: true,
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

        let posBuilder = this.overlay
            .position()
            .flexibleConnectedTo(anchor)
            .withPositions([
                {
                    originX: 'end',
                    originY: 'bottom',
                    overlayX: 'end',
                    overlayY: 'top',
                    offsetY,
                },
                ...(withFlip
                    ? [
                          {
                              originX: 'end' as const,
                              originY: 'top' as const,
                              overlayX: 'end' as const,
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

        this.overlayRef = this.overlay.create({
            positionStrategy: posBuilder,
            hasBackdrop: true,
            backdropClass: 'cdk-overlay-transparent-backdrop',
            scrollStrategy,
            ...(cfg?.panelClass ? { panelClass: cfg.panelClass } : {}),
        });

        this.backdropSub = this.overlayRef.backdropClick().subscribe(() => this.close());
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
