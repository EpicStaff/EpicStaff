import { AfterViewInit, Directive, ElementRef, inject, input, NgZone, OnDestroy } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

@Directive({
    selector: '[appTooltipOnOverflow][matTooltip]',
    standalone: true,
})
export class TooltipOnOverflowDirective implements AfterViewInit, OnDestroy {
    readonly appTooltipOnOverflow = input<string>('');

    private readonly hostRef = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly tooltip = inject(MatTooltip);
    private readonly ngZone = inject(NgZone);

    private resizeObserver: ResizeObserver | null = null;
    private mutationObserver: MutationObserver | null = null;
    private frameId: number | null = null;

    ngAfterViewInit(): void {
        this.tooltip.disabled = true;
        this.ngZone.runOutsideAngular(() => {
            const host = this.hostRef.nativeElement;
            this.resizeObserver = new ResizeObserver(() => this.schedule());
            this.resizeObserver.observe(host);
            this.mutationObserver = new MutationObserver(() => this.schedule());
            this.mutationObserver.observe(host, { childList: true, subtree: true, characterData: true });
            this.schedule();
        });
    }

    private target(): HTMLElement {
        const selector = this.appTooltipOnOverflow();
        if (selector) {
            const found = this.hostRef.nativeElement.querySelector<HTMLElement>(selector);
            if (found) return found;
        }
        return this.hostRef.nativeElement;
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
            const el = this.target();
            const overflowing = el.scrollWidth > el.clientWidth + 1;
            if (this.tooltip.disabled === overflowing) {
                this.ngZone.run(() => (this.tooltip.disabled = !overflowing));
            }
        });
    }
}
