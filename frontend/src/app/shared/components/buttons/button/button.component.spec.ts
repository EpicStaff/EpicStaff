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

    it('renders the filled danger type as its own class', () => {
        const fixture = TestBed.createComponent(ButtonComponent);
        fixture.componentInstance.type = 'danger';
        fixture.detectChanges();

        const button = (fixture.nativeElement as HTMLElement).querySelector('button');
        expect(button?.classList).toContain('btn-danger');
        expect(button?.classList).not.toContain('btn-outline-danger');
    });
});
