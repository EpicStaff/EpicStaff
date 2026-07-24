import { Directive, ElementRef, HostListener, inject, input } from '@angular/core';

import { MultiSelectComponent } from './multi-select.component';

/**
 * Opens a sibling `<app-multi-select>` when the host element is clicked and
 * anchors the dropdown overlay to that host element.
 *
 * Usage:
 * ```html
 * <app-multi-select #ms [hideTrigger]="true" ...>
 *     <button [appMultiSelectTrigger]="ms">Filter</button>
 * </app-multi-select>
 * ```
 */
@Directive({
    selector: '[appMultiSelectTrigger]',
})
export class MultiSelectTriggerDirective {
    private readonly elementRef = inject(ElementRef<HTMLElement>);

    readonly multiSelect = input.required<MultiSelectComponent>({ alias: 'appMultiSelectTrigger' });

    @HostListener('click')
    onClick(): void {
        const ms = this.multiSelect();
        if (ms.isOpen()) {
            ms.close();
        } else {
            ms.openAt(this.elementRef.nativeElement);
        }
    }
}
