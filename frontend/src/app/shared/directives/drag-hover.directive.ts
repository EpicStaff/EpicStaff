import { computed, Directive, ElementRef, inject, input, OnDestroy, output, signal } from '@angular/core';

/**
 * Spring-loaded hover for native HTML5 drags: emits `dragHover` once after the
 * dragged item stays over the host for `dragHoverDelay` ms. Leaving the host
 * (or dropping) before the delay cancels the pending emit.
 *
 * `isHovering` is true while an emit is pending, for hover feedback (`exportAs: 'appDragHover'`).
 * While `dragHoverDisabled` is true the host ignores drags and a pending emit is dropped, e.g.
 * when the kind of drag the host cares about ends.
 */
@Directive({
    selector: '[appDragHover]',
    exportAs: 'appDragHover',
    host: {
        '(dragenter)': 'scheduleHover()',
        '(dragover)': 'scheduleHover()',
        '(dragleave)': 'onDragLeave($event)',
        '(drop)': 'cancelHover()',
    },
})
export class DragHoverDirective implements OnDestroy {
    readonly dragHoverDelay = input<number>(400);
    readonly dragHoverDisabled = input<boolean>(false);

    readonly dragHover = output<void>();

    private readonly pending = signal<boolean>(false);
    readonly isHovering = computed(() => this.pending() && !this.dragHoverDisabled());

    private readonly elementRef = inject<ElementRef<HTMLElement>>(ElementRef);
    private timer: ReturnType<typeof setTimeout> | null = null;

    scheduleHover(): void {
        if (this.dragHoverDisabled()) return;
        this.pending.set(true);
        if (this.timer != null) return;
        this.timer = setTimeout(() => {
            this.timer = null;
            this.pending.set(false);
            // Disabled while waiting (e.g. the drag ended): drop the emit; the next dragover re-arms.
            if (this.dragHoverDisabled()) return;
            this.dragHover.emit();
        }, this.dragHoverDelay());
    }

    onDragLeave(event: DragEvent): void {
        const related = event.relatedTarget as Node | null;
        if (related && this.elementRef.nativeElement.contains(related)) return;
        this.cancelHover();
    }

    cancelHover(): void {
        this.pending.set(false);
        if (this.timer != null) {
            clearTimeout(this.timer);
            this.timer = null;
        }
    }

    ngOnDestroy(): void {
        this.cancelHover();
    }
}
