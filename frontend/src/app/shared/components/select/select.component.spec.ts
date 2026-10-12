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
});
