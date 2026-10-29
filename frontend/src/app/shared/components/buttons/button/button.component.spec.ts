import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ButtonComponent } from './button.component';

// jsdom has no ResizeObserver; the collapse-on-overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Uses the button as its consumers do: a `(click)` on the host element. */
@Component({
    imports: [ButtonComponent],
    template: `<app-button
        [ariaDisabled]="isAriaDisabled()"
        (click)="hostClicks.set(hostClicks() + 1)"
        >Save</app-button
    >`,
})
class ButtonHostComponent {
    readonly isAriaDisabled = signal(false);
    readonly hostClicks = signal(0);
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

    it.each([
        ['is not marked disabled by default', {}, null],
        ['marks its button disabled for assistive technology', { ariaDisabled: true }, 'true'],
    ])('%s, and keeps it focusable', (_case, inputs, ariaDisabled) => {
        const button = render(inputs);

        expect(button.getAttribute('aria-disabled')).toBe(ariaDisabled);
        expect(button.disabled).toBe(false);
    });

    it.each<[description: string, isAriaDisabled: boolean, hostClicks: number, pageClicks: number]>([
        ['reaches the host and the page while enabled', false, 1, 1],
        ['reaches neither the host nor the page while aria-disabled, and the button keeps the focus', true, 0, 0],
    ])('a click %s', (_description, isAriaDisabled, hostClicks, pageClicks) => {
        const fixture = TestBed.createComponent(ButtonHostComponent);
        fixture.componentInstance.isAriaDisabled.set(isAriaDisabled);
        fixture.detectChanges();
        const button = (fixture.nativeElement as HTMLElement).querySelector('button') as HTMLButtonElement;
        let pageClickCount = 0;
        const onPageClick = (): void => {
            pageClickCount++;
        };
        document.addEventListener('click', onPageClick);

        button.focus();
        button.click();

        document.removeEventListener('click', onPageClick);
        expect(fixture.componentInstance.hostClicks()).toBe(hostClicks);
        expect(pageClickCount).toBe(pageClicks);
        expect(document.activeElement).toBe(button);
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
