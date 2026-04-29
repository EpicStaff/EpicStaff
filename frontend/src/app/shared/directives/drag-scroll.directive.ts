import { Directive, ElementRef, HostListener, inject } from '@angular/core';

@Directive({
    selector: '[appDragScroll]',
    standalone: true,
    host: {
        style: 'user-select: none; touch-action: pan-y;',
    },
})
export class DragScrollDirective {
    private static readonly THRESHOLD = 4;

    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;

    private startX = 0;
    private startScroll = 0;
    private pointerId: number | null = null;
    private moved = false;
    private lastDragMoved = false;

    @HostListener('pointerdown', ['$event'])
    onPointerDown(event: PointerEvent): void {
        if (event.button !== 0) return;
        this.startX = event.clientX;
        this.startScroll = this.host.scrollLeft;
        this.pointerId = event.pointerId;
        this.moved = false;
        this.lastDragMoved = false;
    }

    @HostListener('pointermove', ['$event'])
    onPointerMove(event: PointerEvent): void {
        if (this.pointerId === null) return;
        const dx = event.clientX - this.startX;
        if (!this.moved && Math.abs(dx) > DragScrollDirective.THRESHOLD) {
            this.moved = true;
            this.lastDragMoved = true;
            this.host.setPointerCapture(this.pointerId);
        }
        if (this.moved) {
            this.host.scrollLeft = this.startScroll - dx;
            event.preventDefault();
        }
    }

    onPointerUp(): void {
        if (this.pointerId === null) return;
        if (this.host.hasPointerCapture(this.pointerId)) {
            this.host.releasePointerCapture(this.pointerId);
        }
        this.pointerId = null;
    }

    @HostListener('click', ['$event'])
    onClick(event: MouseEvent): void {
        if (this.lastDragMoved) {
            event.preventDefault();
            event.stopPropagation();
            this.lastDragMoved = false;
        }
    }

    @HostListener('dragstart', ['$event'])
    onDragStart(event: DragEvent): void {
        event.preventDefault();
    }
}
