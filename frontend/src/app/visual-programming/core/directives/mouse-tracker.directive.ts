import { DOCUMENT } from '@angular/common';
import { Directive, EventEmitter, Inject, NgZone, OnDestroy, OnInit, Output } from '@angular/core';

@Directive({
    selector: '[appMouseTracker]',
    standalone: true,
})
export class MouseTrackerDirective implements OnInit, OnDestroy {
    @Output() mousePosition = new EventEmitter<{ x: number; y: number }>();

    private unlistenFn?: () => void;

    constructor(
        private ngZone: NgZone,
        @Inject(DOCUMENT) private document: Document
    ) {}

    ngOnInit(): void {
        this.setupMouseTracking();
    }

    private setupMouseTracking(): void {
        this.ngZone.runOutsideAngular(() => {
            const mouseMoveHandler = (event: MouseEvent) => {
                this.mousePosition.emit({
                    x: event.clientX,
                    y: event.clientY,
                });
            };

            document.addEventListener('mousemove', mouseMoveHandler);

            this.unlistenFn = () => {
                document.removeEventListener('mousemove', mouseMoveHandler);
            };
        });
    }

    ngOnDestroy(): void {
        if (this.unlistenFn) {
            this.unlistenFn();
        }
    }
}
