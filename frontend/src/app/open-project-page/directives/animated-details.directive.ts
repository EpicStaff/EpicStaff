import { AfterViewInit, Directive, ElementRef, Renderer2 } from '@angular/core';

@Directive({
    selector: '[appAnimatedDetails]',
    standalone: true,
})
export class AccordionDetailsDirective implements AfterViewInit {
    constructor(
        private el: ElementRef,
        private renderer: Renderer2
    ) {}

    ngAfterViewInit() {
        const details = this.el.nativeElement as HTMLDetailsElement;
        const summary = details.querySelector('summary') as HTMLElement;

        // Handle clicks on add button
        summary.addEventListener('click', (e) => {
            if ((e.target as HTMLElement).closest('.add-task')) {
                e.preventDefault();
                e.stopPropagation();
            }
        });

        // Optional: Add an attribute when details is open
        details.addEventListener('toggle', () => {
            if (details.open) {
                this.renderer.addClass(details, 'is-open');
            } else {
                this.renderer.removeClass(details, 'is-open');
            }
        });
    }
}
