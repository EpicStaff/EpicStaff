import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { CollapseOnOverflowDirective } from './collapse-on-overflow.directive';
import { TooltipWhenCollapsedDirective } from './tooltip-when-collapsed.directive';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({
    imports: [CollapseOnOverflowDirective, MatTooltip, TooltipWhenCollapsedDirective],
    template: `
        <button
            [appCollapseOnOverflow]="true"
            appTooltipWhenCollapsed
            matTooltip="Export"
        >
            <span class="btn-content">Export</span>
        </button>
    `,
})
class HostComponent {}

describe('TooltipWhenCollapsedDirective', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

    it('enables the tooltip only while the button is collapsed to its icon', () => {
        const fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
        const button = fixture.debugElement.query(By.css('button'));
        const tooltip = button.injector.get(MatTooltip);
        const collapse = button.injector.get(CollapseOnOverflowDirective);
        expect(tooltip.disabled).toBe(true);

        collapse.collapseOnOverflowChange.emit(true);
        expect(tooltip.disabled).toBe(false);

        collapse.collapseOnOverflowChange.emit(false);
        expect(tooltip.disabled).toBe(true);
    });
});
