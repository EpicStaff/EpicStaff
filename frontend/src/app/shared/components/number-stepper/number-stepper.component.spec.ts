import { ComponentFixture, TestBed } from '@angular/core/testing';

import { NumberStepperComponent } from './number-stepper.component';

function blurEmptyField(allowEmpty: boolean): number | null {
    const fixture = TestBed.createComponent(NumberStepperComponent);
    fixture.componentRef.setInput('integer', true);
    fixture.componentRef.setInput('min', 5);
    fixture.componentRef.setInput('allowEmpty', allowEmpty);
    fixture.componentRef.setInput('value', null);
    fixture.detectChanges();

    (fixture.nativeElement as HTMLElement).querySelector('input')!.dispatchEvent(new Event('blur'));
    return fixture.componentInstance.value();
}

describe('NumberStepperComponent blur in integer mode', () => {
    it('keeps a cleared field empty when allowEmpty is set', () => {
        expect(blurEmptyField(true)).toBeNull();
    });

    it('fills a cleared field with min by default', () => {
        expect(blurEmptyField(false)).toBe(5);
    });
});

function renderStepper(value: number | null): ComponentFixture<NumberStepperComponent> {
    const fixture = TestBed.createComponent(NumberStepperComponent);
    fixture.componentRef.setInput('alwaysShowButtons', true);
    fixture.componentRef.setInput('min', 0);
    fixture.componentRef.setInput('max', 10);
    fixture.componentRef.setInput('step', 2);
    fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
    return fixture;
}

function stepperButton(
    fixture: ComponentFixture<NumberStepperComponent>,
    name: 'Increase' | 'Decrease'
): HTMLButtonElement {
    return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(`button[aria-label="${name}"]`)!;
}

/** Clicks the button (Enter or Space on a focused button clicks it too) and returns what the stepper emitted. */
function clickStep(
    fixture: ComponentFixture<NumberStepperComponent>,
    name: 'Increase' | 'Decrease'
): (number | null)[] {
    const emitted: (number | null)[] = [];
    fixture.componentInstance.changed.subscribe((value) => emitted.push(value));
    stepperButton(fixture, name).click();
    fixture.detectChanges();
    return emitted;
}

describe('NumberStepperComponent step buttons', () => {
    it('are in the Tab order', () => {
        const fixture = renderStepper(4);

        expect(stepperButton(fixture, 'Increase').tabIndex).toBe(0);
        expect(stepperButton(fixture, 'Decrease').tabIndex).toBe(0);
    });

    it('step on click', () => {
        expect(clickStep(renderStepper(4), 'Increase')).toEqual([6]);
        expect(clickStep(renderStepper(4), 'Decrease')).toEqual([2]);
    });

    it('keep the focus in the input when pressed with the mouse', () => {
        const mousedown = new MouseEvent('mousedown', { bubbles: true, cancelable: true });

        stepperButton(renderStepper(4), 'Increase').dispatchEvent(mousedown);

        expect(mousedown.defaultPrevented).toBe(true);
    });

    it.each<[string, number, 'Increase' | 'Decrease']>([
        ['Increase at max', 10, 'Increase'],
        ['Decrease at min', 0, 'Decrease'],
    ])('mark %s as disabled without taking it out of the Tab order, and emit nothing', (_case, value, name) => {
        const fixture = renderStepper(value);
        const button = stepperButton(fixture, name);

        expect(button.getAttribute('aria-disabled')).toBe('true');
        expect(button.disabled).toBe(false);
        expect(clickStep(fixture, name)).toEqual([]);
    });

    it('show at a hover-only size once the focus is in the control', () => {
        const fixture = TestBed.createComponent(NumberStepperComponent);
        fixture.componentRef.setInput('size', 'md');
        fixture.detectChanges();
        expect(stepperButton(fixture, 'Increase')).toBeNull();

        (fixture.nativeElement as HTMLElement)
            .querySelector('input')!
            .dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
        fixture.detectChanges();

        expect(stepperButton(fixture, 'Increase')).not.toBeNull();
    });
});

describe('NumberStepperComponent arrow keys', () => {
    it('leave the value alone at the bound, emitting nothing', () => {
        const fixture = renderStepper(10);
        const emitted: (number | null)[] = [];
        fixture.componentInstance.changed.subscribe((value) => emitted.push(value));

        (fixture.nativeElement as HTMLElement)
            .querySelector('input')!
            .dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', cancelable: true }));

        expect(emitted).toEqual([]);
        expect(fixture.componentInstance.value()).toBe(10);
    });
});
