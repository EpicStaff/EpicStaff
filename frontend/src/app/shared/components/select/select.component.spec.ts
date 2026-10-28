import { TestBed } from '@angular/core/testing';

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

    it.each([
        ['shows the selected tip in the trigger when opted in', true, 'Default'],
        ['keeps the trigger to the name by default', false, undefined],
    ])('%s', (_case, showTipInTrigger, expectedTip) => {
        const fixture = TestBed.createComponent(SelectComponent);
        fixture.componentRef.setInput('items', [{ name: 'One', tip: 'Default', value: 1 }]);
        fixture.componentRef.setInput('selectedValue', 1);
        fixture.componentRef.setInput('showTipInTrigger', showTipInTrigger);
        fixture.detectChanges();

        const tip = (fixture.nativeElement as HTMLElement).querySelector('.selector__btn .selector__tip');

        expect(tip?.textContent?.trim()).toBe(expectedTip);
    });

    // The trigger names itself after the external label, then its own text, so the selected value is read too.
    it('labels the trigger by the given label and its own text', () => {
        const fixture = TestBed.createComponent(SelectComponent);
        fixture.componentRef.setInput('items', [{ name: 'One', value: 1 }]);
        fixture.componentRef.setInput('ariaLabelledby', 'retention-label');
        fixture.detectChanges();

        const trigger = (fixture.nativeElement as HTMLElement).querySelector('.selector__btn') as HTMLButtonElement;

        expect(trigger.getAttribute('aria-labelledby')).toBe(`retention-label ${trigger.id}`);
        expect(trigger.id).not.toBe('');
    });

    it('leaves aria-labelledby off when no label is given', () => {
        const fixture = TestBed.createComponent(SelectComponent);
        fixture.componentRef.setInput('items', [{ name: 'One', value: 1 }]);
        fixture.detectChanges();

        const trigger = (fixture.nativeElement as HTMLElement).querySelector('.selector__btn') as HTMLButtonElement;

        expect(trigger.hasAttribute('aria-labelledby')).toBe(false);
    });
});
