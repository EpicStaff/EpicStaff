import { Directive, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';

import { CollapseOnOverflowDirective } from './collapse-on-overflow.directive';

/**
 * Shows a button's `matTooltip` only while `appCollapseOnOverflow` has collapsed it to its icon: with its label
 * visible, a tooltip repeating that label adds nothing.
 */
@Directive({
    selector: '[appTooltipWhenCollapsed][appCollapseOnOverflow][matTooltip]',
})
export class TooltipWhenCollapsedDirective implements OnInit {
    private readonly tooltip = inject(MatTooltip);
    private readonly collapse = inject(CollapseOnOverflowDirective);

    constructor() {
        this.collapse.collapseOnOverflowChange
            .pipe(takeUntilDestroyed())
            .subscribe((collapsed) => (this.tooltip.disabled = !collapsed));
    }

    ngOnInit(): void {
        this.tooltip.disabled = true;
    }
}
