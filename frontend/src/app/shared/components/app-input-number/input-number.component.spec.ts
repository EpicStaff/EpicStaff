import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { By } from '@angular/platform-browser';

import { InputNumberComponent } from './input-number.component';

@Component({
    imports: [ReactiveFormsModule, InputNumberComponent],
    template: `<app-input-number
        [formControl]="control"
        [allowDecimal]="allowDecimal()"
    />`,
})
class HostComponent {
    readonly allowDecimal = signal(false);
    readonly control = new FormControl<number | null>(null);
}

describe('InputNumberComponent', () => {
    let fixture: ComponentFixture<HostComponent>;

    function createHost(allowDecimal: boolean): HostComponent {
        fixture = TestBed.createComponent(HostComponent);
        fixture.componentInstance.allowDecimal.set(allowDecimal);
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    function nativeInput(): HTMLInputElement {
        return fixture.debugElement.query(By.css('input')).nativeElement as HTMLInputElement;
    }

    function pressKey(key: string): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key, cancelable: true });
        nativeInput().dispatchEvent(event);
        return event;
    }

    /** Types text the browser cannot parse: a number input then reports an empty value and `validity.badInput`. */
    function typeMalformedNumber(): void {
        const input = nativeInput();
        Object.defineProperty(input, 'validity', { value: { badInput: true }, configurable: true });
        input.value = '';
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function typeNumber(text: string): void {
        const input = nativeInput();
        Object.defineProperty(input, 'validity', { value: { badInput: false }, configurable: true });
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    describe('without allowDecimal', () => {
        it('blocks the decimal point, as before', () => {
            createHost(false);

            expect(pressKey('.').defaultPrevented).toBe(true);
        });

        it('still lets digits through', () => {
            createHost(false);

            expect(pressKey('7').defaultPrevented).toBe(false);
        });

        it('does not report a validation error for an empty value', () => {
            const host = createHost(false);

            typeMalformedNumber();

            expect(host.control.errors).toBeNull();
            expect(host.control.value).toBeNull();
        });
    });

    describe('with allowDecimal', () => {
        it('lets the decimal point through', () => {
            createHost(true);

            expect(pressKey('.').defaultPrevented).toBe(false);
        });

        it('still blocks other non-digit keys', () => {
            createHost(true);

            expect(pressKey(',').defaultPrevented).toBe(true);
        });

        it('passes a typed decimal to the control', () => {
            const host = createHost(true);

            typeNumber('2.5');

            expect(host.control.value).toBe(2.5);
            expect(host.control.valid).toBe(true);
        });

        it('flags malformed text as invalidNumber instead of clearing the value', () => {
            const host = createHost(true);
            typeNumber('2.5');

            typeMalformedNumber();

            expect(host.control.hasError('invalidNumber')).toBe(true);
            expect(host.control.value).toBe(2.5);
        });

        it('clears the error once the text is a valid number again', () => {
            const host = createHost(true);
            typeMalformedNumber();

            typeNumber('1.5');

            expect(host.control.hasError('invalidNumber')).toBe(false);
            expect(host.control.value).toBe(1.5);
        });

        it('clears the error when the form sets a new value', () => {
            const host = createHost(true);
            typeMalformedNumber();

            host.control.setValue(3);

            expect(host.control.valid).toBe(true);
        });
    });
});

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

describe('InputNumberComponent stepping', () => {
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
});
