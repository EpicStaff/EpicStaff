import {
    AfterViewInit,
    contentChild,
    contentChildren,
    Directive,
    ElementRef,
    input,
    NgZone,
    OnDestroy,
    Renderer2,
    signal,
} from '@angular/core';

@Directive({
    selector: '[appOverflowItem]',
})
export class OverflowItemDirective {
    readonly appOverflowLabel = input('');
    constructor(readonly elRef: ElementRef<HTMLElement>) {}
}

@Directive({
    selector: '[appOverflowBadge]',
})
export class OverflowBadgeDirective {
    constructor(readonly elRef: ElementRef<HTMLElement>) {}
}

/**
 * Measures which `appOverflowItem` children fit inside the host and hides the rest.
 * Exposes `overflowCount` signal with the number of hidden items for use in templates.
 *
 * Usage:
 *   <div appOverflowItems #ov="overflowItems">
 *     @for (item of items; track item) {
 *       <span appOverflowItem>{{ item }}</span>
 *     }
 *     <span appOverflowBadge>+{{ ov.overflowCount() }}</span>
 *   </div>
 *
 * The `appOverflowBadge` element is hidden by the directive when all items fit,
 * and shown when some items overflow.
 */
@Directive({
    selector: '[appOverflowItems]',
    exportAs: 'overflowItems',
})
export class OverflowItemsDirective implements AfterViewInit, OnDestroy {
    readonly overflowCount = signal(0);
    readonly hiddenLabels = signal('');

    private readonly items = contentChildren(OverflowItemDirective);
    private readonly badge = contentChild(OverflowBadgeDirective);

    private resizeObserver: ResizeObserver | null = null;
    private mutationObserver: MutationObserver | null = null;
    private frameId: number | null = null;

    constructor(
        private readonly hostRef: ElementRef<HTMLElement>,
        private readonly renderer: Renderer2,
        private readonly ngZone: NgZone
    ) {}

    ngAfterViewInit(): void {
        this.ngZone.runOutsideAngular(() => {
            this.resizeObserver = new ResizeObserver(() => this.schedule());

            // Observe host and all ancestors so column width changes are detected
            let el: HTMLElement | null = this.hostRef.nativeElement;
            while (el && el !== document.body) {
                this.resizeObserver.observe(el);
                el = el.parentElement;
            }

            // Detect when items are added/removed (e.g. @for re-render on data change)
            this.mutationObserver = new MutationObserver(() => this.schedule());
            this.mutationObserver.observe(this.hostRef.nativeElement, { childList: true });

            this.schedule();
            // Second pass after initial paint to catch deferred layout
            setTimeout(() => this.schedule(), 200);
        });
    }

    ngOnDestroy(): void {
        this.resizeObserver?.disconnect();
        this.resizeObserver = null;
        this.mutationObserver?.disconnect();
        this.mutationObserver = null;
        if (this.frameId !== null) {
            cancelAnimationFrame(this.frameId);
            this.frameId = null;
        }
    }

    private schedule(): void {
        if (this.frameId !== null) return;
        this.frameId = requestAnimationFrame(() => {
            this.frameId = null;
            this.evaluate();
        });
    }

    private evaluate(): void {
        const host = this.hostRef.nativeElement;
        const itemEls = this.items().map((d) => d.elRef.nativeElement);
        const badgeEl = this.badge()?.elRef.nativeElement ?? null;

        if (!itemEls.length) return;

        // Reset: show all items, hide badge
        for (const item of itemEls) {
            this.renderer.removeStyle(item, 'display');
        }
        if (badgeEl) this.renderer.setStyle(badgeEl, 'display', 'none');

        const containerWidth = host.clientWidth;
        if (containerWidth === 0) return;

        const gap = parseFloat(getComputedStyle(host).columnGap) || 4;

        // Measure all items (they are all visible at this point)
        const widths = itemEls.map((item) => item.offsetWidth);
        const totalWidth = widths.reduce((sum, w, i) => sum + w + (i > 0 ? gap : 0), 0);

        if (totalWidth <= containerWidth) {
            // Everything fits — no badge needed
            this.ngZone.run(() => {
                this.overflowCount.set(0);
                this.hiddenLabels.set('');
            });
            return;
        }

        // Temporarily show badge to measure its real width
        if (badgeEl) this.renderer.setStyle(badgeEl, 'display', 'inline-flex');
        const badgeWidth = badgeEl ? badgeEl.offsetWidth + gap : 32;
        if (badgeEl) this.renderer.setStyle(badgeEl, 'display', 'none');

        // Find how many items fit alongside the badge
        const available = containerWidth - badgeWidth;
        let accWidth = 0;
        let visibleCount = 0;

        for (let i = 0; i < widths.length; i++) {
            const itemWidth = widths[i] + (i > 0 ? gap : 0);
            if (accWidth + itemWidth <= available) {
                accWidth += itemWidth;
                visibleCount++;
            } else {
                break;
            }
        }

        // Hide items that don't fit
        for (let i = visibleCount; i < itemEls.length; i++) {
            this.renderer.setStyle(itemEls[i], 'display', 'none');
        }

        const hidden = itemEls.length - visibleCount;
        if (badgeEl && hidden > 0) {
            this.renderer.setStyle(badgeEl, 'display', 'inline-flex');
        }

        const labels = this.items()
            .slice(visibleCount)
            .map((d) => d.appOverflowLabel())
            .filter((l) => l)
            .join(', ');

        this.ngZone.run(() => {
            this.overflowCount.set(hidden);
            this.hiddenLabels.set(labels);
        });
    }
}
