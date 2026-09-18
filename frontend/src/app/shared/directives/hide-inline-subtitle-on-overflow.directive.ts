import { AfterViewInit, Directive, ElementRef, input, NgZone, OnDestroy, Renderer2 } from '@angular/core';

@Directive({
    selector: '[appHideInlineSubtitleOnOverflow]',
})
export class HideInlineSubtitleOnOverflowDirective implements AfterViewInit, OnDestroy {
    overflowTitleSelector = input('.title');
    overflowInlineSelector = input('.subtitle-inline');
    overflowTrailingSelector = input<string | undefined>(undefined);
    overflowMeasureSelector = input<string | undefined>(undefined);
    private resizeObserver: ResizeObserver | null = null;
    private removeWindowResizeListener: (() => void) | null = null;
    private removeTransitionEndListener: (() => void) | null = null;
    private removeAnimationEndListener: (() => void) | null = null;
    private mutationObserver: MutationObserver | null = null;
    private frameId: number | null = null;
    private observedTrailing: HTMLElement | null = null;

    constructor(
        private readonly hostRef: ElementRef<HTMLElement>,
        private readonly renderer: Renderer2,
        private readonly ngZone: NgZone
    ) {}

    public ngAfterViewInit(): void {
        this.ngZone.runOutsideAngular(() => {
            const host = this.hostRef.nativeElement;
            const title = this.getTitleElement();
            if (!title) {
                return;
            }

            this.resizeObserver = new ResizeObserver(() => this.scheduleEvaluate());
            this.resizeObserver.observe(title);
            this.resizeObserver.observe(host);
            const measureEl = this.getMeasureElement(host);
            if (measureEl) {
                this.resizeObserver.observe(measureEl);
            }
            this.ensureTrailingObserved();
            this.observeContainerResizes();

            this.removeWindowResizeListener = this.renderer.listen('window', 'resize', () => this.scheduleEvaluate());
            this.removeTransitionEndListener = this.renderer.listen(host, 'transitionend', () =>
                this.scheduleEvaluate()
            );
            this.removeAnimationEndListener = this.renderer.listen(host, 'animationend', () => this.scheduleEvaluate());

            this.mutationObserver = new MutationObserver(() => this.scheduleEvaluate());
            this.mutationObserver.observe(host, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['class', 'style'],
            });

            this.scheduleEvaluate();
            setTimeout(() => this.scheduleEvaluate(), 200);
        });
    }

    public ngOnDestroy(): void {
        this.resizeObserver?.disconnect();
        this.resizeObserver = null;
        this.mutationObserver?.disconnect();
        this.mutationObserver = null;

        if (this.removeWindowResizeListener) {
            this.removeWindowResizeListener();
            this.removeWindowResizeListener = null;
        }
        if (this.removeTransitionEndListener) {
            this.removeTransitionEndListener();
            this.removeTransitionEndListener = null;
        }
        if (this.removeAnimationEndListener) {
            this.removeAnimationEndListener();
            this.removeAnimationEndListener = null;
        }

        if (this.frameId !== null) {
            cancelAnimationFrame(this.frameId);
            this.frameId = null;
        }
    }

    private scheduleEvaluate(): void {
        if (this.frameId !== null) {
            return;
        }

        this.frameId = requestAnimationFrame(() => {
            this.frameId = null;
            this.evaluateOverflow();
        });
    }

    private evaluateOverflow(): void {
        this.ensureTrailingObserved();

        const host = this.hostRef.nativeElement;
        const title = this.getTitleElement();
        const subtitle = host.querySelector<HTMLElement>(this.overflowInlineSelector());
        const trailing = this.getTrailingElement();
        const measureEl = this.getMeasureElement(host) ?? host;

        host.classList.remove('hide-inline-subtitle', 'hide-inline-trailing');

        if (!title) {
            return;
        }

        const availableWidth = this.overflowMeasureSelector()
            ? this.getMaxWidthInParent(measureEl)
            : Math.min(measureEl.clientWidth, this.getMaxWidthInParent(measureEl));
        const gap = trailing ? this.readGap(measureEl) : 0;

        const hintOverflows = (): boolean => title.scrollWidth > availableWidth + 1;

        const trailingOverflows = (): boolean =>
            !!trailing && title.scrollWidth + gap + trailing.offsetWidth > availableWidth + 1;

        if (!trailing) {
            if (subtitle && hintOverflows()) {
                host.classList.add('hide-inline-subtitle');
            }
            return;
        }

        if (trailingOverflows()) {
            host.classList.add('hide-inline-trailing');
            void host.offsetWidth;
        }

        if (subtitle && hintOverflows() && host.classList.contains('hide-inline-trailing')) {
            host.classList.add('hide-inline-subtitle');
        }
    }

    private readGap(host: HTMLElement): number {
        const styles = getComputedStyle(host);
        const parsed = parseFloat(styles.columnGap || styles.gap);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    private getMeasureElement(host: HTMLElement): HTMLElement | null {
        if (!this.overflowMeasureSelector()) {
            return null;
        }
        return host.querySelector<HTMLElement>(this.overflowMeasureSelector()!);
    }

    private getMaxWidthInParent(el: HTMLElement): number {
        const parent = el.parentElement;
        if (!parent) {
            return el.clientWidth;
        }

        const parentRect = parent.getBoundingClientRect();
        const elRect = el.getBoundingClientRect();
        return Math.max(0, Math.floor(parentRect.right - elRect.left));
    }

    private observeContainerResizes(): void {
        if (!this.resizeObserver) {
            return;
        }

        let parent: HTMLElement | null = this.hostRef.nativeElement.parentElement;
        while (parent && parent !== document.body && parent !== document.documentElement) {
            this.resizeObserver.observe(parent);
            parent = parent.parentElement;
        }
    }

    private getTitleElement(): HTMLElement | null {
        return this.hostRef.nativeElement.querySelector<HTMLElement>(this.overflowTitleSelector());
    }

    private getTrailingElement(): HTMLElement | null {
        if (!this.overflowTrailingSelector()) {
            return null;
        }
        return this.hostRef.nativeElement.querySelector<HTMLElement>(this.overflowTrailingSelector()!);
    }

    private ensureTrailingObserved(): void {
        const trailing = this.getTrailingElement();
        if (!trailing || trailing === this.observedTrailing || !this.resizeObserver) {
            return;
        }
        this.resizeObserver.observe(trailing);
        this.observedTrailing = trailing;
    }
}
