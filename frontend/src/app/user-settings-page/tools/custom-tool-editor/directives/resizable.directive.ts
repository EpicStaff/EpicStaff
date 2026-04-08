import { DOCUMENT } from '@angular/common';
import {
    Directive,
    ElementRef,
    EventEmitter,
    Inject,
    NgZone,
    OnDestroy,
    OnInit,
    Output,
    Renderer2,
} from '@angular/core';

@Directive({
    selector: '[appResizable]',
    standalone: true,
})
export class ResizableDirective implements OnInit, OnDestroy {
    @Output() heightChange = new EventEmitter<number>();

    private isResizing = false;
    private startY = 0;
    private startHeight = 0;
    private unlistenPointerMove?: () => void;
    private unlistenPointerUp?: () => void;

    constructor(
        private el: ElementRef,
        private renderer: Renderer2,
        private ngZone: NgZone,
        @Inject(DOCUMENT) private document: Document
    ) {}

    ngOnInit(): void {
        this.renderer.listen(this.el.nativeElement, 'pointerdown', (event: PointerEvent) => this.onResizeStart(event));
    }

    private onResizeStart(event: PointerEvent): void {
        this.isResizing = true;
        this.startY = event.clientY;
        this.startHeight = this.el.nativeElement.previousElementSibling.clientHeight;

        event.preventDefault();

        this.ngZone.runOutsideAngular(() => {
            this.unlistenPointerMove = this.renderer.listen(this.document, 'pointermove', (event: PointerEvent) =>
                this.onPointerMove(event)
            );
            this.unlistenPointerUp = this.renderer.listen(this.document, 'pointerup', () => this.onPointerUp());
        });
    }

    private onPointerMove(event: PointerEvent): void {
        if (!this.isResizing) return;

        const offsetY = event.clientY - this.startY;
        const newHeight = this.startHeight + offsetY;

        if (newHeight > 100) {
            requestAnimationFrame(() => {
                this.ngZone.run(() => {
                    this.heightChange.emit(newHeight);
                });
            });
        }
    }

    private onPointerUp(): void {
        if (this.isResizing) {
            this.isResizing = false;

            if (this.unlistenPointerMove) this.unlistenPointerMove();
            if (this.unlistenPointerUp) this.unlistenPointerUp();
        }
    }

    ngOnDestroy(): void {
        if (this.unlistenPointerMove) this.unlistenPointerMove();
        if (this.unlistenPointerUp) this.unlistenPointerUp();
    }
}
