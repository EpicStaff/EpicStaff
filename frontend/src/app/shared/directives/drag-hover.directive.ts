import { Directive, ElementRef, inject, input, OnDestroy, output } from '@angular/core';

/**
 * Spring-loaded hover for native HTML5 drags: emits `dragHover` once after the
 * dragged item stays over the host for `dragHoverDelay` ms. Leaving the host
 * (or dropping) before the delay cancels the pending emit.
 */
@Directive({
    selector: '[appDragHover]',
    host: {
        '(dragenter)': 'scheduleHover()',
        '(dragover)': 'scheduleHover()',
        '(dragleave)': 'onDragLeave($event)',
        '(drop)': 'cancelHover()',
    },
})
export class DragHoverDirective implements OnDestroy {
    dragHoverDelay = input<number>(400);

    readonly dragHover = output<void>();

    private readonly elementRef = inject<ElementRef<HTMLElement>>(ElementRef);
    private timer: ReturnType<typeof setTimeout> | null = null;

    scheduleHover(): void {
        if (this.timer != null) return;
        this.timer = setTimeout(() => {
            this.timer = null;
            this.dragHover.emit();
        }, this.dragHoverDelay());
    }

    onDragLeave(event: DragEvent): void {
        const related = event.relatedTarget as Node | null;
        if (related && this.elementRef.nativeElement.contains(related)) return;
        this.cancelHover();
    }

    cancelHover(): void {
        if (this.timer != null) {
            clearTimeout(this.timer);
            this.timer = null;
        }
    }

    ngOnDestroy(): void {
        this.cancelHover();
    }
}
