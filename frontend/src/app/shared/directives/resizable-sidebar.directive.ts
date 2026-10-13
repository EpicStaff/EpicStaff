import { computed, Directive, ElementRef, inject, input, NgZone, OnDestroy, OnInit, Renderer2 } from '@angular/core';

import { SidebarCollapseOptions, SidebarWidthOptions, SidebarWidthService } from '../services/sidebar-width.service';

/** Width change per ArrowLeft / ArrowRight press. */
export const SIDEBAR_KEYBOARD_STEP_PX = 16;
/** Width change per Shift + ArrowLeft / ArrowRight press. */
export const SIDEBAR_KEYBOARD_LARGE_STEP_PX = 64;
/** Pointer travel below which a press on the handle counts as a click rather than a drag. */
export const SIDEBAR_CLICK_TOLERANCE_PX = 3;

@Directive({
    selector: '[appResizableSidebar]',
    host: {
        role: 'separator',
        'aria-orientation': 'vertical',
        '[attr.aria-label]': 'sidebarAriaLabel()',
        '[attr.aria-valuenow]': 'currentWidth()',
        '[attr.aria-valuemin]': 'smallestWidth()',
        '[attr.aria-valuemax]': 'sidebarMaxWidth()',
        tabindex: '0',
        '(keydown)': 'onKeydown($event)',
    },
})
export class ResizableSidebarDirective implements OnInit, OnDestroy {
    storageKey = input.required<string>({ alias: 'appResizableSidebar' });
    sidebarTarget = input.required<HTMLElement>();
    sidebarMinWidth = input(220);
    sidebarMaxWidth = input(600);
    /** When set, dragging below the collapse threshold snaps the sidebar to its collapsed width. */
    sidebarCollapse = input<SidebarCollapseOptions | null>(null);
    sidebarAriaLabel = input('Resize sidebar');

    protected readonly currentWidth = computed(() =>
        this.sidebarWidthService.getWidth(this.storageKey(), this.widthOptions())()
    );
    /** The narrowest reachable width: the collapsed width when the sidebar can collapse. */
    protected readonly smallestWidth = computed(() => this.sidebarCollapse()?.collapsedWidth ?? this.sidebarMinWidth());
    private readonly widthOptions = computed<SidebarWidthOptions>(() => ({
        minWidth: this.sidebarMinWidth(),
        maxWidth: this.sidebarMaxWidth(),
        collapse: this.sidebarCollapse(),
    }));

    private isResizing = false;
    private startX = 0;
    private startWidth = 0;
    private hasDragged = false;
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

    /** Window-splitter keyboard support: arrows step, Home/End jump to the ends, Enter toggles collapse. */
    protected onKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter') {
            if (this.sidebarCollapse() !== null) {
                event.preventDefault();
                this.toggleCollapsed();
            }
            return;
        }
        const targetWidth = this.keyboardTargetWidth(event);
        if (targetWidth === null) {
            return;
        }
        event.preventDefault();
        this.sidebarWidthService.setWidth(this.storageKey(), targetWidth, this.widthOptions());
        this.sidebarWidthService.commitWidth(this.storageKey());
    }

    private keyboardTargetWidth(event: KeyboardEvent): number | null {
        const width = this.currentWidth();
        const minWidth = this.sidebarMinWidth();
        const collapse = this.sidebarCollapse();
        const isCollapsed = collapse !== null && width <= collapse.collapsedWidth;
        const step = event.shiftKey ? SIDEBAR_KEYBOARD_LARGE_STEP_PX : SIDEBAR_KEYBOARD_STEP_PX;

        switch (event.key) {
            case 'ArrowRight':
                return isCollapsed ? minWidth : width + step;
            case 'ArrowLeft':
                // Stop at the minimum width first; only the next press collapses, so no step skips it.
                if (collapse !== null && width <= minWidth) {
                    return collapse.collapsedWidth;
                }
                return Math.max(minWidth, width - step);
            case 'Home':
                return this.smallestWidth();
            case 'End':
                return this.sidebarMaxWidth();
            default:
                return null;
        }
    }

    private onResizeStart(event: PointerEvent): void {
        this.isResizing = true;
        this.startX = event.clientX;
        this.startWidth = this.sidebarTarget().getBoundingClientRect().width;
        this.hasDragged = false;
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
        const travel = event.clientX - this.startX;
        if (!this.hasDragged && Math.abs(travel) < SIDEBAR_CLICK_TOLERANCE_PX) {
            return;
        }
        this.hasDragged = true;
        this.pendingWidth = this.startWidth + travel;
        if (this.frameId !== null) {
            return;
        }
        this.frameId = requestAnimationFrame(() => {
            this.frameId = null;
            this.ngZone.run(() => {
                this.sidebarWidthService.setWidth(this.storageKey(), this.pendingWidth, this.widthOptions());
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
            this.ngZone.run(() => {
                if (this.hasDragged) {
                    this.sidebarWidthService.commitWidth(this.storageKey());
                } else {
                    this.toggleCollapsed();
                }
            });
        }
        this.unlistenPointerMove?.();
        this.unlistenPointerUp?.();
        this.unlistenPointerCancel?.();
    }

    /** Enter, or a click (press without drag) on the handle, opens or closes a collapsible sidebar. */
    private toggleCollapsed(): void {
        this.sidebarWidthService.toggleCollapsed(this.storageKey(), this.widthOptions());
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
}
