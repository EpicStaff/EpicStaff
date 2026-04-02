import { AfterViewInit, Directive, ElementRef, EventEmitter, Input, NgZone, OnDestroy, Output } from '@angular/core';

@Directive({
    selector: '[appCollapseOnOverflow]',
    standalone: true,
})
export class CollapseOnOverflowDirective implements AfterViewInit, OnDestroy {
    @Input('appCollapseOnOverflow') public collapseOnOverflowEnabled = true;
    @Input() public collapseOnOverflowTarget = '.btn-content';
    @Input() public collapseOnOverflowClass = 'is-collapsed';
    @Input() public collapseOnOverflowRequireSelector = '';
    @Input() public collapseOnOverflowCheckExternalClip = true;

    @Output() public collapseOnOverflowChange = new EventEmitter<boolean>();

    private resizeObserver: ResizeObserver | null = null;
    private mutationObserver: MutationObserver | null = null;
    private frameId: number | null = null;
    private collapsed = false;

    constructor(
        private readonly hostRef: ElementRef<HTMLElement>,
        private readonly ngZone: NgZone
    ) {}

    public ngAfterViewInit(): void {
        this.ngZone.runOutsideAngular(() => {
            const host = this.hostRef.nativeElement;

            this.resizeObserver = new ResizeObserver(() => this.scheduleEvaluate());
            this.resizeObserver.observe(host);

            this.observeAncestorResizes(host);

            this.mutationObserver = new MutationObserver(() => this.scheduleEvaluate());
            this.mutationObserver.observe(host, {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
            });

            this.scheduleEvaluate();
            setTimeout(() => this.scheduleEvaluate(), 0);
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

    private scheduleEvaluate(): void {
        if (this.frameId !== null) {
            return;
        }

        this.frameId = requestAnimationFrame(() => {
            this.frameId = null;
            this.evaluate();
        });
    }

    private evaluate(): void {
        const host = this.hostRef.nativeElement;

        if (!this.collapseOnOverflowEnabled) {
            this.setCollapsed(false);
            return;
        }

        if (this.collapseOnOverflowRequireSelector && !host.querySelector(this.collapseOnOverflowRequireSelector)) {
            this.setCollapsed(false);
            return;
        }

        const target = host.querySelector<HTMLElement>(this.collapseOnOverflowTarget);
        if (!target) {
            this.setCollapsed(false);
            return;
        }

        host.classList.remove(this.collapseOnOverflowClass);

        const horizontalOverflow = target.scrollWidth - target.clientWidth > 1;
        const verticalOverflow = target.scrollHeight - target.clientHeight > 1;
        const externallyClipped = this.collapseOnOverflowCheckExternalClip ? this.isExternallyClipped(host) : false;

        this.setCollapsed(horizontalOverflow || verticalOverflow || externallyClipped);
    }

    private setCollapsed(next: boolean): void {
        const host = this.hostRef.nativeElement;
        host.classList.toggle(this.collapseOnOverflowClass, next);

        if (this.collapsed === next) {
            return;
        }

        this.collapsed = next;
        this.ngZone.run(() => {
            this.collapseOnOverflowChange.emit(next);
        });
    }

    private isExternallyClipped(host: HTMLElement): boolean {
        const rect = host.getBoundingClientRect();
        const visibleWidth = this.getVisibleWidth(rect);
        return visibleWidth + 1 < rect.width;
    }

    private getVisibleWidth(targetRect: DOMRect): number {
        let left = Math.max(0, targetRect.left);
        let right = Math.min(window.innerWidth, targetRect.right);

        let ancestor: HTMLElement | null = this.hostRef.nativeElement.parentElement;
        while (ancestor) {
            const overflowX = window.getComputedStyle(ancestor).overflowX;
            if (overflowX !== 'visible') {
                const rect = ancestor.getBoundingClientRect();
                left = Math.max(left, rect.left);
                right = Math.min(right, rect.right);
            }
            ancestor = ancestor.parentElement;
        }

        return Math.max(0, right - left);
    }

    private observeAncestorResizes(fromElement: HTMLElement): void {
        if (!this.resizeObserver) {
            return;
        }

        let parent: HTMLElement | null = fromElement.parentElement;
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
}
