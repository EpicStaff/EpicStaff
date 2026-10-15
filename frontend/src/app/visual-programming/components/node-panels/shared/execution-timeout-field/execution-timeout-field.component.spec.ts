import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { InputNumberComponent, TooltipComponent } from '@shared/components';

import { ExecutionTimeoutLimits } from '../../../../core/models/execution-timeout-limits.model';
import { FlowReadOnlyService } from '../../../../services/flow-readonly.service';
import { ExecutionTimeoutFieldComponent } from './execution-timeout-field.component';
import { ExecutionTimeoutFormField, MAX_STORABLE_SECONDS } from './execution-timeout-form-field';

const LIMITS: ExecutionTimeoutLimits = { minSeconds: 5, defaultSeconds: 120, maxSeconds: 3600 };

describe('ExecutionTimeoutFieldComponent', () => {
    let fixture: ComponentFixture<ExecutionTimeoutFieldComponent>;
    const isReadOnly = signal(false);

    beforeEach(() => {
        isReadOnly.set(false);
        TestBed.configureTestingModule({
            providers: [{ provide: FlowReadOnlyService, useValue: { isReadOnly } }],
        });
    });

    function render(field: ExecutionTimeoutFormField): void {
        fixture = TestBed.createComponent(ExecutionTimeoutFieldComponent);
        fixture.componentRef.setInput('field', field);
        fixture.detectChanges();
    }

    /** The hours, minutes and seconds inputs, in that order. */
    function parts(): InputNumberComponent[] {
        return fixture.debugElement
            .queryAll(By.directive(InputNumberComponent))
            .map((debugElement) => debugElement.componentInstance as InputNumberComponent);
    }

    function shownParts(): (number | null)[] {
        return parts().map((part) => part.value());
    }

    function type(partIndex: number, value: number | null): void {
        parts()[partIndex].onInputChange(value as number);
        fixture.detectChanges();
    }

    function message(kind: 'error' | 'warning'): string | null {
        const element = (fixture.nativeElement as HTMLElement).querySelector(`.execution-timeout__message--${kind}`);
        return element?.textContent?.trim() ?? null;
    }

    function tooltipText(): string {
        return (
            fixture.debugElement.query(By.directive(TooltipComponent)).componentInstance as TooltipComponent
        ).tooltipText();
    }

    it('splits the timeout into hours, minutes and seconds', () => {
        render(new ExecutionTimeoutFormField(3725, LIMITS));

        expect(shownParts()).toEqual([1, 2, 5]);
        expect(parts().map((part) => part.ariaLabel())).toEqual(['Hours', 'Minutes', 'Seconds']);
    });

    it('names the group of parts for assistive technologies, and announces its message', () => {
        render(new ExecutionTimeoutFormField(90, LIMITS));
        const host = fixture.nativeElement as HTMLElement;

        const group = host.querySelector('[role="group"]');
        expect(group?.getAttribute('aria-label')).toBe('Execution timeout');
        expect(group?.querySelectorAll('input')).toHaveLength(3);
        expect(host.querySelector('[aria-live="polite"]')).not.toBeNull();
    });

    it('shows the default for a code without a timeout', () => {
        render(new ExecutionTimeoutFormField(undefined, LIMITS));

        expect(shownParts()).toEqual([0, 2, 0]);
    });

    it('puts the parts back together into seconds on an edit', () => {
        const field = new ExecutionTimeoutFormField(125, LIMITS);
        render(field);

        type(1, 30);

        expect(field.control.value).toBe(30 * 60 + 5);
        expect(field.value).toBe(30 * 60 + 5);
    });

    it('counts an emptied part as zero', () => {
        const field = new ExecutionTimeoutFormField(3725, LIMITS);
        render(field);

        type(0, null);

        expect(field.control.value).toBe(2 * 60 + 5);
    });

    it('normalizes the parts once an edit overflows one of them', () => {
        const field = new ExecutionTimeoutFormField(60, LIMITS);
        render(field);

        type(2, 90);

        expect(field.control.value).toBe(150);
        expect(shownParts()).toEqual([0, 2, 30]);
    });

    it('rounds a pasted fraction to whole seconds', () => {
        const field = new ExecutionTimeoutFormField(60, LIMITS);
        render(field);

        type(2, 0.6);

        expect(field.control.value).toBe(61);
        expect(shownParts()).toEqual([0, 1, 1]);
    });

    it('caps a huge edit at what the backend can store when there is no maximum', () => {
        const field = new ExecutionTimeoutFormField(60, { ...LIMITS, maxSeconds: null });
        render(field);

        type(0, 10_000_000);

        expect(field.control.value).toBe(MAX_STORABLE_SECONDS);
    });

    it('names the range in its tooltip', () => {
        render(new ExecutionTimeoutFormField(90, LIMITS));

        expect(tooltipText()).toContain('(5 s to 1 h)');
    });

    it('names only the minimum in its tooltip when there is no maximum', () => {
        render(new ExecutionTimeoutFormField(90, { ...LIMITS, maxSeconds: null }));

        expect(tooltipText()).toContain('(at least 5 s)');
    });

    it('says the timeout is below the minimum, and marks every part invalid', () => {
        const field = new ExecutionTimeoutFormField(90, LIMITS);
        render(field);

        type(1, 0);
        type(2, 3);

        expect(field.control.value).toBe(3);
        expect(field.control.invalid).toBe(true);
        expect(message('error')).toBe('Must be at least 5 s.');
        expect(parts().every((part) => part.isInvalid())).toBe(true);
    });

    it('shows no message for a timeout within the limits', () => {
        render(new ExecutionTimeoutFormField(LIMITS.maxSeconds!, LIMITS));

        expect(message('error')).toBeNull();
        expect(message('warning')).toBeNull();
    });

    it('warns that a stored timeout above the maximum runs for the maximum, without an error', () => {
        const field = new ExecutionTimeoutFormField(7200, LIMITS);
        render(field);

        expect(shownParts()).toEqual([2, 0, 0]);
        expect(field.control.valid).toBe(true);
        expect(message('warning')).toBe('Runs for at most 1 h, the current limit.');
        expect(message('error')).toBeNull();
    });

    it('caps an edit above the maximum at the maximum, and shows the capped value', () => {
        const field = new ExecutionTimeoutFormField(90, LIMITS);
        render(field);

        type(0, 5);

        expect(field.control.value).toBe(LIMITS.maxSeconds);
        expect(shownParts()).toEqual([1, 0, 0]);
        expect(message('warning')).toBeNull();
    });

    it('resets a typed part even when the capped total equals the one before', () => {
        const field = new ExecutionTimeoutFormField(LIMITS.maxSeconds!, LIMITS);
        render(field);

        type(0, 3);

        expect(field.control.value).toBe(LIMITS.maxSeconds);
        expect(shownParts()).toEqual([1, 0, 0]);
    });

    it('shows the capped value in every part, without the warning, once a timeout stored above the maximum is edited', () => {
        render(new ExecutionTimeoutFormField(7200, LIMITS));

        type(2, 1);

        expect(shownParts()).toEqual([1, 0, 0]);
        expect(message('warning')).toBeNull();
    });

    it('follows a value set on the control from outside', () => {
        const field = new ExecutionTimeoutFormField(90, LIMITS);
        render(field);

        field.control.setValue(3661);
        fixture.detectChanges();

        expect(shownParts()).toEqual([1, 1, 1]);
    });

    it('disables every part while the flow is read-only, and follows it', () => {
        render(new ExecutionTimeoutFormField(90, LIMITS));
        expect(parts().some((part) => part.isDisabled())).toBe(false);

        isReadOnly.set(true);
        fixture.detectChanges();

        expect(parts().every((part) => part.isDisabled())).toBe(true);
    });
});
