import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { InputNumberComponent } from '@shared/components';

import { createExecutionTimeoutField, ExecutionTimeoutFormField } from './execution-timeout-control';
import { ExecutionTimeoutFieldComponent } from './execution-timeout-field.component';

describe('ExecutionTimeoutFieldComponent', () => {
    let fixture: ComponentFixture<ExecutionTimeoutFieldComponent>;

    function render(field: ExecutionTimeoutFormField, perExecutionNote?: string): void {
        fixture = TestBed.createComponent(ExecutionTimeoutFieldComponent);
        fixture.componentRef.setInput('field', field);
        if (perExecutionNote !== undefined) fixture.componentRef.setInput('perExecutionNote', perExecutionNote);
        fixture.detectChanges();
    }

    function input(): InputNumberComponent {
        return fixture.debugElement.query(By.directive(InputNumberComponent)).componentInstance as InputNumberComponent;
    }

    function warning(): string | null {
        const element = (fixture.nativeElement as HTMLElement).querySelector('.input__message--warning');
        return element?.textContent?.trim() ?? null;
    }

    function errors(): string[] {
        return fixture.debugElement
            .queryAll(By.css('.validation-errors__item'))
            .map((item) => (item.nativeElement as HTMLElement).textContent?.trim() ?? '');
    }

    it('shows the timeout, bounded from 1 minute to the ceiling', () => {
        render(createExecutionTimeoutField(5, 45));

        expect(input().value()).toBe(5);
        expect(input().min()).toBe(1);
        expect(input().max()).toBe(45);
        expect(input().required()).toBe(true);
        expect(input().tooltipText()).toContain('(1 to 45)');
    });

    it('adds which executions the limit applies to, for a node that runs its code several times', () => {
        render(createExecutionTimeoutField(5, 45), 'Each step separately.');

        expect(input().tooltipText()).toMatch(/\(1 to 45\)\. Each step separately\.$/);
    });

    it('writes an edit into the form control', () => {
        const field = createExecutionTimeoutField(5, 45);
        render(field);

        input().onInputChange(12);

        expect(field.control.value).toBe(12);
    });

    it('warns that a timeout saved under a higher ceiling will be saved as the ceiling, without an error', () => {
        render(createExecutionTimeoutField(90, 45));

        expect(input().isInvalid()).toBe(false);
        expect(input().isAboveWarning()).toBe(true);
        expect(warning()).toBe('Will be saved as 45 min, the current limit.');
        expect(errors()).toEqual([]);
    });

    it('shows no warning up to the ceiling, and stops the stepper there', () => {
        render(createExecutionTimeoutField(45, 45));

        expect(warning()).toBeNull();
        expect(input().canStepUp()).toBe(false);
    });

    it('drops the warning once the value is brought down to the ceiling', () => {
        render(createExecutionTimeoutField(90, 45));

        input().onStep(-1);
        fixture.detectChanges();

        expect(input().value()).toBe(45);
        expect(warning()).toBeNull();
    });

    it('caps a typed timeout above the ceiling at the ceiling', () => {
        const field = createExecutionTimeoutField(5, 45);
        render(field);

        input().onInputChange(90);
        fixture.detectChanges();

        expect(field.control.value).toBe(45);
        expect(input().value()).toBe(45);
    });

    it('gives the input an accessible name that contains its visible label', () => {
        render(createExecutionTimeoutField(5, 45));

        const label = (fixture.nativeElement as HTMLElement).querySelector('.tooltip-label-text')?.textContent?.trim();
        const accessibleName = (fixture.nativeElement as HTMLElement)
            .querySelector('input')
            ?.getAttribute('aria-label');

        expect(label).toBe('Execution Timeout (min)');
        expect(accessibleName).toContain(label);
    });

    it('says a fractional timeout must be whole once the field was touched', () => {
        const field = createExecutionTimeoutField(5, 45);
        render(field);

        field.control.setValue(1.5);
        field.control.markAsTouched();
        fixture.detectChanges();

        expect(errors()).toEqual(['Must be a whole number.']);
    });
});
