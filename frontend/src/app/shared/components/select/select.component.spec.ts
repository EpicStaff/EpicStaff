import { getDebugNode } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';

import { SelectComponent } from './select.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('SelectComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    // A button without a type submits its form: opening the dropdown would save the enclosing form.
    it('renders a trigger that does not submit an enclosing form', () => {
        const fixture = TestBed.createComponent(SelectComponent);
        fixture.componentRef.setInput('items', [{ name: 'One', value: 1 }]);
        fixture.detectChanges();

        const trigger = (fixture.nativeElement as HTMLElement).querySelector('.selector__btn') as HTMLButtonElement;

        expect(trigger.type).toBe('button');
    });

    // The trigger already shows the selected value: a tooltip only adds something once the value is cut.
    it.each([
        ['fits', 100, true],
        ['is cut by the ellipsis', 300, false],
    ])('offers the selected value as a tooltip only when it %s', (_case, scrollWidth, disabled) => {
        // Frames wait until the text has its (hand-set) size: jsdom lays nothing out.
        const frames: FrameRequestCallback[] = [];
        vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => frames.push(callback));
        const fixture = TestBed.createComponent(SelectComponent);
        fixture.componentRef.setInput('items', [{ name: 'A rather long option name', value: 1 }]);
        fixture.componentInstance.writeValue(1);
        fixture.detectChanges();
        const text = (fixture.nativeElement as HTMLElement).querySelector('.selector__text') as HTMLElement;
        Object.defineProperty(text, 'scrollWidth', { configurable: true, value: scrollWidth });
        Object.defineProperty(text, 'clientWidth', { configurable: true, value: 100 });

        frames.splice(0).forEach((frame) => frame(0));

        const tooltip = getDebugNode(text)!.injector.get(MatTooltip);
        expect(tooltip.message).toBe('A rather long option name');
        expect(tooltip.disabled).toBe(disabled);
    });
});
