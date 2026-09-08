import { Directive, ElementRef, inject, input, NgZone, OnDestroy, OnInit, output, Renderer2 } from '@angular/core';

import { SectionHeightService } from '../services/section-height.service';

@Directive({
    selector: '[appResizableSection]',
    host: {
        role: 'separator',
        'aria-orientation': 'horizontal',
        '[attr.aria-label]': 'sectionAriaLabel()',
        tabindex: '0',
    },
})
export class ResizableSectionDirective implements OnInit, OnDestroy {
    storageKey = input.required<string>({ alias: 'appResizableSection' });
    sectionTarget = input.required<HTMLElement>();
    sectionMinHeight = input(80);
    sectionMaxHeight = input(600);
    /** Optional per-drag cap, e.g. to stop growth once a sibling section would be squeezed below its own minimum. Read once, at drag start. */
    sectionMaxHeightFn = input<(() => number) | null>(null);
    sectionAriaLabel = input('Resize section');

    /** Fired as soon as a drag starts, so a collapsed section can be expanded to receive the new height. */
    readonly dragStart = output<void>();

    private isResizing = false;
    private hasMoved = false;
    private startY = 0;
    private startHeight = 0;
    private effectiveMaxHeight = 600;
    private pendingHeight = 0;
    private frameId: number | null = null;
    private pointerId: number | null = null;
    private unlistenPointerMove?: () => void;
    private unlistenPointerUp?: () => void;
    private unlistenPointerCancel?: () => void;

    private readonly el = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly renderer = inject(Renderer2);
    private readonly ngZone = inject(NgZone);
    private readonly sectionHeightService = inject(SectionHeightService);

    ngOnInit(): void {
        this.ngZone.runOutsideAngular(() => {
            this.renderer.listen(this.el.nativeElement, 'pointerdown', (event: PointerEvent) =>
                this.onResizeStart(event)
            );
        });
    }

    private onResizeStart(event: PointerEvent): void {
        this.isResizing = true;
        this.hasMoved = false;
        this.startY = event.clientY;
        this.startHeight = this.sectionTarget().getBoundingClientRect().height;
        const dynamicMax = this.sectionMaxHeightFn()?.();
        this.effectiveMaxHeight =
            dynamicMax != null ? Math.min(this.sectionMaxHeight(), dynamicMax) : this.sectionMaxHeight();
        this.pointerId = event.pointerId;
        this.el.nativeElement.setPointerCapture(event.pointerId);
        this.renderer.addClass(this.el.nativeElement, 'is-dragging');
        this.document.body.style.cursor = 'row-resize';
        this.document.body.style.userSelect = 'none';
        event.preventDefault();

        this.ngZone.run(() => {
            // Pin the height immediately (e.g. to 0 for a still-collapsed section) so expanding it
            // doesn't briefly flash at its full natural content height before the first drag frame lands.
            this.sectionHeightService.setHeight(
                this.storageKey(),
                this.startHeight,
                this.sectionMinHeight(),
                this.effectiveMaxHeight
            );
            this.dragStart.emit();
        });

        this.unlistenPointerMove = this.renderer.listen(this.document, 'pointermove', (e: PointerEvent) =>
            this.onPointerMove(e)
        );
        this.unlistenPointerUp = this.renderer.listen(this.document, 'pointerup', () => this.onPointerEnd(true));
        this.unlistenPointerCancel = this.renderer.listen(this.document, 'pointercancel', () =>
            this.onPointerEnd(false)
        );
    }

    private onPointerMove(event: PointerEvent): void {
        if (!this.isResizing) {
            return;
        }
        this.hasMoved = true;
        this.pendingHeight = this.startHeight + (event.clientY - this.startY);
        if (this.frameId !== null) {
            return;
        }
        this.frameId = requestAnimationFrame(() => {
            this.frameId = null;
            this.applyPendingHeight();
        });
    }

    private applyPendingHeight(): void {
        this.ngZone.run(() => {
            this.sectionHeightService.setHeight(
                this.storageKey(),
                this.pendingHeight,
                this.sectionMinHeight(),
                this.effectiveMaxHeight
            );
        });
    }

    private onPointerEnd(commit: boolean): void {
        if (!this.isResizing) {
            return;
        }
        this.isResizing = false;
        this.releasePointerCapture();
        this.resetDragState();
        if (this.frameId !== null) {
            // A pointerup can land between rAF frames — flush the last move so we don't commit stale height.
            cancelAnimationFrame(this.frameId);
            this.frameId = null;
            this.applyPendingHeight();
        }
        if (commit && this.hasMoved) {
            this.ngZone.run(() => this.sectionHeightService.commitHeight(this.storageKey()));
        }
        this.unlistenPointerMove?.();
        this.unlistenPointerUp?.();
        this.unlistenPointerCancel?.();
    }

    private releasePointerCapture(): void {
        if (this.pointerId !== null && this.el.nativeElement.hasPointerCapture(this.pointerId)) {
            this.el.nativeElement.releasePointerCapture(this.pointerId);
        }
        this.pointerId = null;
    }

    /** Undoes everything onResizeStart applied: the dragging class and the body cursor/selection lock. */
    private resetDragState(): void {
        this.renderer.removeClass(this.el.nativeElement, 'is-dragging');
        this.document.body.style.cursor = '';
        this.document.body.style.userSelect = '';
    }

    private get document(): Document {
        return this.el.nativeElement.ownerDocument;
    }

    ngOnDestroy(): void {
        if (this.frameId !== null) {
            cancelAnimationFrame(this.frameId);
        }
        if (this.isResizing) {
            this.isResizing = false;
            this.releasePointerCapture();
            this.resetDragState();
        }
        this.unlistenPointerMove?.();
        this.unlistenPointerUp?.();
        this.unlistenPointerCancel?.();
    }
}
