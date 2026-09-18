import { Directive, ElementRef, HostListener, inject } from '@angular/core';

import { SelectDropdownComponent } from './select-dropdown.component';

@Directive({
    selector: '[appSelectDropdownTrigger]',
})
export class SelectDropdownTriggerDirective {
    readonly elementRef = inject(ElementRef<HTMLElement>);
    private readonly host = inject(SelectDropdownComponent, { host: true });

    @HostListener('click')
    onClick(): void {
        this.host.toggle();
    }
}
