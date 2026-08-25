import { Directive, ElementRef, HostListener, inject } from '@angular/core';

@Directive({
    selector: '[appEnterBlur]',
    standalone: true,
})
export class EnterBlurDirective {
    private readonly el = inject(ElementRef<HTMLElement>);

    @HostListener('keydown.enter', ['$event'])
    onEnter(event: Event): void {
        if (!(event instanceof KeyboardEvent) || event.shiftKey) return;
        event.preventDefault();
        this.el.nativeElement.blur();
    }
}
