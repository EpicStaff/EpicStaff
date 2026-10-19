import { ComponentFixture, TestBed } from '@angular/core/testing';

import { InputNumberComponent } from './input-number.component';

function render(value: number): ComponentFixture<InputNumberComponent> {
    const fixture = TestBed.createComponent(InputNumberComponent);
    fixture.componentRef.setInput('alwaysShowSteps', true);
    fixture.componentRef.setInput('min', 10);
    fixture.componentRef.setInput('max', 100);
    fixture.componentRef.setInput('stepSize', 10);
    fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
    return fixture;
}

function renderWithError(value: number): HTMLElement {
    const fixture = TestBed.createComponent(InputNumberComponent);
    fixture.componentRef.setInput('max', 10);
    fixture.componentRef.setInput('errorMessage', 'At most 10');
    fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

// The step buttons react to mousedown, not click, so the input keeps focus while stepping.
function step(fixture: ComponentFixture<InputNumberComponent>, direction: 'plus' | 'minus'): number | null {
    const emitted: (number | null)[] = [];
    fixture.componentInstance.changed.subscribe((value) => emitted.push(value));
    const button = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(
        `.input__step--${direction}`
    );
    button?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    fixture.detectChanges();
    return emitted.at(-1) ?? null;
}

describe('InputNumberComponent', () => {
    it('adds the step to a typed value that is not a multiple of the step', () => {
        expect(step(render(15), 'plus')).toBe(25);
        expect(step(render(25), 'minus')).toBe(15);
    });

    it('clamps the stepped value to min and max', () => {
        expect(step(render(15), 'minus')).toBe(10);
        expect(step(render(95), 'plus')).toBe(100);
    });

    it('names the field for assistive technology', () => {
        const fixture = render(10);
        fixture.componentRef.setInput('ariaLabel', 'Sessions to display');
        fixture.detectChanges();
        const field = (fixture.nativeElement as HTMLElement).querySelector('input');
        expect(field?.getAttribute('aria-label')).toBe('Sessions to display');
    });

    it('marks the input invalid and points it at the error text', () => {
        const host = renderWithError(11);
        const input = host.querySelector('input') as HTMLInputElement;
        const describedBy = input.getAttribute('aria-describedby') ?? '';

        expect(input.getAttribute('aria-invalid')).toBe('true');
        expect(host.querySelector(`#${describedBy}`)?.textContent?.trim()).toBe('At most 10');
    });

    it('leaves a valid input without an error description', () => {
        const input = renderWithError(5).querySelector('input') as HTMLInputElement;

        expect(input.getAttribute('aria-invalid')).toBe('false');
        expect(input.hasAttribute('aria-describedby')).toBe(false);
    });
});
