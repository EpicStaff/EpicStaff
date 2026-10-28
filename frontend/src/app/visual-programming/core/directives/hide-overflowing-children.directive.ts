import { AfterViewInit, Directive, ElementRef, inject, NgZone, OnDestroy } from '@angular/core';

const HIDEABLE_CHILD_SELECTOR = ':scope > [data-hide-on-overflow]';

/**
 * Hides the host's children marked with `data-hide-on-overflow`, leftmost first, until the rest fits
 * the host's width, and shows them again once they fit; unmarked children always stay. The host must
 * span the whole available width and lay its children out flush right (`justify-content: flex-end`),
 * so its own size tracks the free space and an overflow spills past its left edge.
 */
@Directive({
    selector: '[appHideOverflowingChildren]',
})
export class HideOverflowingChildrenDirective implements AfterViewInit, OnDestroy {
    private readonly host: HTMLElement = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
    private readonly ngZone = inject(NgZone);

    private resizeObserver: ResizeObserver | null = null;
    private mutationObserver: MutationObserver | null = null;
    private frameId: number | null = null;

    public ngAfterViewInit(): void {
        this.ngZone.runOutsideAngular(() => {
            this.resizeObserver = new ResizeObserver(() => this.scheduleEvaluate());
            this.observeSizes();

            // Children come and go with @if and permission checks; each needs its size observed.
            this.mutationObserver = new MutationObserver(() => {
                this.observeSizes();
                this.scheduleEvaluate();
            });
            this.mutationObserver.observe(this.host, { childList: true });

            this.scheduleEvaluate();
        });
    }

    public ngOnDestroy(): void {
        this.resizeObserver?.disconnect();
        this.resizeObserver = null;

        this.mutationObserver?.disconnect();
        this.mutationObserver = null;

        if (this.frameId !== null) {
            cancelAnimationFrame(this.frameId);
            this.frameId = null;
        }
    }

    private observeSizes(): void {
        if (!this.resizeObserver) {
            return;
        }

        this.resizeObserver.disconnect();
        this.resizeObserver.observe(this.host);
        for (const child of Array.from(this.host.children)) {
            this.resizeObserver.observe(child);
        }
    }

    private scheduleEvaluate(): void {
        if (this.frameId !== null) {
            return;
        }

        this.frameId = requestAnimationFrame(() => {
            this.frameId = null;
            this.evaluate();
        });
    }

    // Starts from everything shown so that a widened host brings hidden children back. The result is
    // the same on every run for the same width, so the resize notifications it causes settle at once.
    private evaluate(): void {
        const hideableChildren = Array.from(this.host.querySelectorAll<HTMLElement>(HIDEABLE_CHILD_SELECTOR));
        for (const child of hideableChildren) {
            child.style.removeProperty('display');
        }

        for (const child of hideableChildren) {
            if (!this.isOverflowing()) {
                break;
            }
            child.style.display = 'none';
        }
    }

    // Overflow to the left is not scrollable, so scrollWidth misses it; compare edges instead.
    private isOverflowing(): boolean {
        const leftmostVisibleChild = Array.from(this.host.children).find((child) => child.getClientRects().length > 0);
        if (!leftmostVisibleChild) {
            return false;
        }
        return leftmostVisibleChild.getBoundingClientRect().left < this.host.getBoundingClientRect().left - 1;
    }
}
