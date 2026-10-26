import { TestBed } from '@angular/core/testing';

import { ButtonComponent } from './button.component';

// jsdom has no ResizeObserver; the collapse-on-overflow directive only needs it to exist.
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

    it('renders the outline-danger type as its own class', () => {
        expect(render({ type: 'outline-danger' }).classList).toContain('btn-outline-danger');
    });

    // display: none would drop the label from the accessibility tree and leave the icon-only button nameless.
    it('keeps its label for screen readers once it collapses to the icon', () => {
        const fixture = TestBed.createComponent(ButtonComponent);
        fixture.componentRef.setInput('leftIcon', 'plus');
        fixture.detectChanges();

        fixture.componentInstance.onCollapseChange(true);
        fixture.detectChanges();

        const button = (fixture.nativeElement as HTMLElement).querySelector('button') as HTMLButtonElement;
        const label = button.querySelector('.btn-content') as HTMLElement;
        expect(button.classList).toContain('btn--only-icon');
        expect(getComputedStyle(label).display).not.toBe('none');
        expect(getComputedStyle(label).position).toBe('absolute');
    });
});
