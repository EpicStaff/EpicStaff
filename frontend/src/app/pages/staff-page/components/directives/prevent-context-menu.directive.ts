import { Directive, ElementRef, OnInit } from '@angular/core';

@Directive({
    standalone: true,
    selector: '[appPreventContextMenu]',
})
export class PreventContextMenuDirective implements OnInit {
    constructor(private el: ElementRef) {}

    ngOnInit(): void {
        this.el.nativeElement.addEventListener('contextmenu', (event: MouseEvent) => {
            event.preventDefault();
        });
    }
}
