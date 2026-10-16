import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { TooltipOnOverflowDirective } from './tooltip-on-overflow.directive';

// jsdom has no ResizeObserver and lays nothing out: the sizes are set by hand below.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({
    imports: [MatTooltip, TooltipOnOverflowDirective],
    template: '<span appTooltipOnOverflow matTooltip="Full text">Text</span>',
})
class HostComponent {}

function tooltipFor(
    size: Record<'scrollWidth' | 'clientWidth' | 'scrollHeight' | 'clientHeight', number>,
    clamp = ''
): MatTooltip {
    const fixture = TestBed.createComponent(HostComponent);
    const span = fixture.debugElement.query(By.directive(TooltipOnOverflowDirective));
    for (const [name, value] of Object.entries(size)) {
        Object.defineProperty(span.nativeElement, name, { configurable: true, value });
    }
    (span.nativeElement as HTMLElement).style.setProperty('-webkit-line-clamp', clamp);
    fixture.detectChanges();
    return span.injector.get(MatTooltip);
}

describe('TooltipOnOverflowDirective', () => {
    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
            callback(0);
            return 1;
        });
    });
    afterEach(() => vi.unstubAllGlobals());

    it('shows the tooltip when the text is cut at the side', () => {
        const tooltip = tooltipFor({ scrollWidth: 200, clientWidth: 100, scrollHeight: 20, clientHeight: 20 });
        expect(tooltip.disabled).toBe(false);
    });

    it('shows the tooltip when line-clamped text is cut at the bottom', () => {
        const tooltip = tooltipFor({ scrollWidth: 100, clientWidth: 100, scrollHeight: 90, clientHeight: 60 }, '3');
        expect(tooltip.disabled).toBe(false);
    });

    it('keeps the tooltip off for a fixed-height host taller inside but not clamped', () => {
        const tooltip = tooltipFor({ scrollWidth: 100, clientWidth: 100, scrollHeight: 24, clientHeight: 20 });
        expect(tooltip.disabled).toBe(true);
    });
});
