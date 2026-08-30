import { Directive, ElementRef, inject, input, NgZone, OnDestroy, OnInit, Renderer2 } from '@angular/core';

import { SidebarWidthService } from '../services/sidebar-width.service';

@Directive({
    selector: '[appResizableSidebar]',
    host: {
        role: 'separator',
        'aria-orientation': 'vertical',
        '[attr.aria-label]': 'sidebarAriaLabel()',
        tabindex: '0',
    },
})
export class ResizableSidebarDirective implements OnInit, OnDestroy {
    storageKey = input.required<string>({ alias: 'appResizableSidebar' });
    sidebarTarget = input.required<HTMLElement>();
    sidebarMinWidth = input(220);
    sidebarMaxWidth = input(600);
    sidebarAriaLabel = input('Resize sidebar');

    private isResizing = false;
    private startX = 0;
    private startWidth = 0;
    private pendingWidth = 0;
    private frameId: number | null = null;
    private pointerId: number | null = null;
    private unlistenPointerMove?: () => void;
    private unlistenPointerUp?: () => void;
    private unlistenPointerCancel?: () => void;

    private readonly el = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly renderer = inject(Renderer2);
    private readonly ngZone = inject(NgZone);
    private readonly sidebarWidthService = inject(SidebarWidthService);

    ngOnInit(): void {
        this.ngZone.runOutsideAngular(() => {
            this.renderer.listen(this.el.nativeElement, 'pointerdown', (event: PointerEvent) =>
                this.onResizeStart(event)
            );
        });
    }

    private onResizeStart(event: PointerEvent): void {
        this.isResizing = true;
        this.startX = event.clientX;
        this.startWidth = this.sidebarTarget().getBoundingClientRect().width;
        this.pointerId = event.pointerId;
        this.el.nativeElement.setPointerCapture(event.pointerId);
        this.document.body.style.cursor = 'col-resize';
        this.document.body.style.userSelect = 'none';
        event.preventDefault();

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
        this.pendingWidth = this.startWidth + (event.clientX - this.startX);
        if (this.frameId !== null) {
            return;
        }
        this.frameId = requestAnimationFrame(() => {
            this.frameId = null;
            this.ngZone.run(() => {
                this.sidebarWidthService.setWidth(
                    this.storageKey(),
                    this.pendingWidth,
                    this.sidebarMinWidth(),
                    this.sidebarMaxWidth()
                );
            });
        });
    }

    private onPointerEnd(commit: boolean): void {
        if (!this.isResizing) {
            return;
        }
        this.isResizing = false;
        this.releasePointerCapture();
        this.resetBodyStyles();
        if (commit) {
            this.ngZone.run(() => this.sidebarWidthService.commitWidth(this.storageKey()));
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

    private resetBodyStyles(): void {
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
            this.resetBodyStyles();
        }
        this.unlistenPointerMove?.();
        this.unlistenPointerUp?.();
        this.unlistenPointerCancel?.();
    }
}
