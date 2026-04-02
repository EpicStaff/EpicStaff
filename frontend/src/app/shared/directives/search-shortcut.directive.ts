import { Directive, ElementRef, EventEmitter, HostListener, NgZone, Output, Renderer2 } from '@angular/core';

@Directive({
    selector: '[appSearchShortcut]',
    standalone: true,
})
export class SearchShortcutDirective {
    @Output() public clearByShortcut = new EventEmitter<void>();

    constructor(
        private el: ElementRef<HTMLInputElement>,
        private ngZone: NgZone,
        private renderer: Renderer2
    ) {}

    @HostListener('window:keydown', ['$event'])
    handleGlobalKeydown(event: KeyboardEvent) {
        // Ctrl+K or Cmd+K
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
            event.preventDefault();
            event.stopPropagation();
            this.renderer.selectRootElement(this.el.nativeElement).focus();
            this.renderer.selectRootElement(this.el.nativeElement).select();
        }
    }

    @HostListener('keydown', ['$event'])
    handleInputKeydown(event: KeyboardEvent) {
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            this.ngZone.run(() => {
                this.clearByShortcut.emit();
                this.renderer.selectRootElement(this.el.nativeElement).blur();
            });
        }
    }
}
