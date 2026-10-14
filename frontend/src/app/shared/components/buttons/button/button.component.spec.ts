import { TestBed } from '@angular/core/testing';

import { ButtonComponent } from './button.component';

// The label collapses to its icon on overflow, which jsdom cannot measure.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('ButtonComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

    afterEach(() => vi.unstubAllGlobals());

    function render(inputs: Record<string, unknown> = {}): HTMLButtonElement {
        const fixture = TestBed.createComponent(ButtonComponent);
        Object.entries(inputs).forEach(([name, value]) => fixture.componentRef.setInput(name, value));
        fixture.detectChanges();
        return (fixture.nativeElement as HTMLElement).querySelector('button') as HTMLButtonElement;
    }

    it('puts no description on its button by default', () => {
        expect(render().hasAttribute('aria-describedby')).toBe(false);
    });

    it('passes a description to its button, which is what gets the focus', () => {
        expect(render({ ariaDescribedby: 'save-warning' }).getAttribute('aria-describedby')).toBe('save-warning');
    });
});
