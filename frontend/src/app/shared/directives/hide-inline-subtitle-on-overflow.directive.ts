import { AfterViewInit, Directive, ElementRef, NgZone, OnDestroy, Renderer2 } from '@angular/core';

@Directive({
    selector: '[appHideInlineSubtitleOnOverflow]',
    standalone: true,
})
export class HideInlineSubtitleOnOverflowDirective implements AfterViewInit, OnDestroy {
    private resizeObserver: ResizeObserver | null = null;
    private removeWindowResizeListener: (() => void) | null = null;
    private removeTransitionEndListener: (() => void) | null = null;
    private removeAnimationEndListener: (() => void) | null = null;
    private mutationObserver: MutationObserver | null = null;
    private frameId: number | null = null;

    constructor(
        private readonly hostRef: ElementRef<HTMLElement>,
        private readonly renderer: Renderer2,
        private readonly ngZone: NgZone
    ) {}

    public ngAfterViewInit(): void {
        this.ngZone.runOutsideAngular(() => {
            const title = this.getTitleElement();
            if (!title) {
                return;
            }

            this.resizeObserver = new ResizeObserver(() => this.scheduleEvaluate());
            this.resizeObserver.observe(title);
            this.resizeObserver.observe(this.hostRef.nativeElement);
            this.observeAncestorResizes();
            this.removeWindowResizeListener = this.renderer.listen('window', 'resize', () => this.scheduleEvaluate());
            this.removeTransitionEndListener = this.renderer.listen('document', 'transitionend', () =>
                this.scheduleEvaluate()
            );
            this.removeAnimationEndListener = this.renderer.listen('document', 'animationend', () =>
                this.scheduleEvaluate()
            );

            this.mutationObserver = new MutationObserver(() => this.scheduleEvaluate());
            this.mutationObserver.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['class', 'style'],
            });
            this.mutationObserver.observe(document.body, {
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
        const host = this.hostRef.nativeElement;
        const title = this.getTitleElement();
        const subtitle = host.querySelector<HTMLElement>('.subtitle-inline');
        if (!title || !subtitle) {
            return;
        }

        host.classList.remove('hide-inline-subtitle');
        const horizontalOverflow = title.scrollWidth - title.clientWidth > 1;
        const shouldHideSubtitle = horizontalOverflow;

        if (shouldHideSubtitle) {
            host.classList.add('hide-inline-subtitle');
        }
    }

    private observeAncestorResizes(): void {
        if (!this.resizeObserver) {
            return;
        }

        let parent: HTMLElement | null = this.hostRef.nativeElement.parentElement;
        while (parent) {
            this.resizeObserver.observe(parent);
            if (parent === document.body) {
                break;
            }
            parent = parent.parentElement;
        }

        this.resizeObserver.observe(document.documentElement);
        this.resizeObserver.observe(document.body);
    }

    private getTitleElement(): HTMLElement | null {
        return this.hostRef.nativeElement.querySelector<HTMLElement>('.title');
    }
}
