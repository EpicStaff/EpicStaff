import { Directive, ElementRef, HostListener, inject, input } from '@angular/core';

import { SelectComponent } from './select.component';

/**
 * Opens a sibling `<app-select>` when the host element is clicked and
 * anchors the dropdown overlay to that host element.
 *
 * Usage:
 * ```html
 * <app-select #sel [hideTrigger]="true" ...>
 *     <button [appSelectTrigger]="sel">Filter</button>
 * </app-select>
 * ```
 */
@Directive({
    selector: '[appSelectTrigger]',
})
export class SelectTriggerDirective {
    private readonly elementRef = inject(ElementRef<HTMLElement>);

    readonly select = input.required<SelectComponent>({ alias: 'appSelectTrigger' });

    @HostListener('click')
    onClick(): void {
        const s = this.select();
        if (s.open()) {
            s.close();
        } else {
            s.openAt(this.elementRef.nativeElement);
        }
    }
}
