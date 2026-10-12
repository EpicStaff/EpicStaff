import { TestBed } from '@angular/core/testing';

import { InputNumberComponent } from './input-number.component';

function render(value: number): HTMLElement {
    const fixture = TestBed.createComponent(InputNumberComponent);
    fixture.componentRef.setInput('max', 10);
    fixture.componentRef.setInput('errorMessage', 'At most 10');
    fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

describe('InputNumberComponent', () => {
    it('marks the input invalid and points it at the error text', () => {
        const host = render(11);
        const input = host.querySelector('input') as HTMLInputElement;
        const describedBy = input.getAttribute('aria-describedby') ?? '';

        expect(input.getAttribute('aria-invalid')).toBe('true');
        expect(host.querySelector(`#${describedBy}`)?.textContent?.trim()).toBe('At most 10');
    });

    it('leaves a valid input without an error description', () => {
        const input = render(5).querySelector('input') as HTMLInputElement;

        expect(input.getAttribute('aria-invalid')).toBe('false');
        expect(input.hasAttribute('aria-describedby')).toBe(false);
    });
});
