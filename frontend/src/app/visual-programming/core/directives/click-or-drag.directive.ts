import {
  Directive,
  EventEmitter,
  Output,
  NgZone,
  ElementRef,
  Renderer2,
  OnDestroy,
  OnInit,
} from '@angular/core';

@Directive({
  selector: '[clickOrDrag]',
  standalone: true,
})
export class ClickOrDragDirective implements OnInit, OnDestroy {
  @Output() actualClick = new EventEmitter<void>();

  private isDragging = false;
  private mouseDownPos = { x: 0, y: 0 };
  private readonly dragThreshold = 5; // pixels to move before considering it a drag
  private unlisteners: (() => void)[] = [];

  constructor(
    private ngZone: NgZone,
    private elementRef: ElementRef,
    private renderer: Renderer2
  ) {}

  ngOnInit(): void {
    this.ngZone.runOutsideAngular(() => {
      this.unlisteners.push(
        this.renderer.listen(
          this.elementRef.nativeElement,
          'mousedown',
          (event: MouseEvent) => {
            this.isDragging = false;
            this.mouseDownPos = { x: event.clientX, y: event.clientY };
          }
        )
      );

      this.unlisteners.push(
        this.renderer.listen(
          this.elementRef.nativeElement,
          'mousemove',
          (event: MouseEvent) => {
            if (!this.mouseDownPos) return;

            const deltaX = Math.abs(event.clientX - this.mouseDownPos.x);
            const deltaY = Math.abs(event.clientY - this.mouseDownPos.y);

            if (deltaX > this.dragThreshold || deltaY > this.dragThreshold) {
              this.isDragging = true;
            }
          }
        )
      );

      this.unlisteners.push(
        this.renderer.listen(
          this.elementRef.nativeElement,
          'mouseup',
          (event: MouseEvent) => {
            if (
              !this.isDragging &&
              !event.ctrlKey &&
              !event.shiftKey &&
              !event.altKey &&
              !event.metaKey
            ) {
              this.ngZone.run(() => {
                this.actualClick.emit();
              });
            }
            this.resetState();
          }
        )
      );

      this.unlisteners.push(
        this.renderer.listen(
          this.elementRef.nativeElement,
          'mouseleave',
          () => {
            this.resetState();
          }
        )
      );
    });
  }

  ngOnDestroy(): void {
    this.unlisteners.forEach((unlisten) => unlisten());
    this.unlisteners = [];
  }

  private resetState(): void {
    this.mouseDownPos = { x: 0, y: 0 };
    this.isDragging = false;
  }
}
