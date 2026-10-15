import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { TooltipComponent } from '@shared/components';

import { FlowReadOnlyService } from '../../../../services/flow-readonly.service';
import { TEST_EXECUTION_TIMEOUT_LIMITS } from '../../../../utils/testing/execution-timeout-limits.testing';
import { ExecutionTimeoutFieldComponent, UNREADABLE_DURATION_MESSAGE } from './execution-timeout-field.component';
import { ExecutionTimeoutFormField, MAX_STORABLE_SECONDS } from './execution-timeout-form-field';

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

    function input(): HTMLInputElement {
        return (fixture.nativeElement as HTMLElement).querySelector('input')!;
    }

    function type(text: string): void {
        input().value = text;
        input().dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function blur(): void {
        input().dispatchEvent(new Event('blur'));
        fixture.detectChanges();
    }

    function pressEnter(): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });
        input().dispatchEvent(event);
        fixture.detectChanges();
        return event;
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

    it('shows the timeout as hh:mm:ss in one input', () => {
        render(new ExecutionTimeoutFormField(3725, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect((fixture.nativeElement as HTMLElement).querySelectorAll('input')).toHaveLength(1);
        expect(input().value).toBe('01:02:05');
        expect(input().placeholder).toBe('hh:mm:ss');
    });

    it('shows the default for a code without a timeout', () => {
        render(new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(input().value).toBe('00:02:00');
    });

    it('shows hours past 99 in full when there is no maximum', () => {
        render(new ExecutionTimeoutFormField(100 * 3600, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null }));

        expect(input().value).toBe('100:00:00');
    });

    it('names the input, describes it by its message, and announces the message', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        const host = fixture.nativeElement as HTMLElement;

        expect(input().getAttribute('aria-label')).toContain('Execution timeout');
        const messageRegion = host.querySelector('[aria-live="polite"]');
        expect(messageRegion).not.toBeNull();
        expect(input().getAttribute('aria-describedby')).toBe(messageRegion!.id);
        expect(input().getAttribute('aria-invalid')).toBe('false');
    });

    it('gives every field its own message id', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        const firstId = input().getAttribute('aria-describedby');

        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(input().getAttribute('aria-describedby')).not.toBe(firstId);
    });

    it('does not edit while typing', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('00:0');

        expect(field.control.value).toBe(600);
        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('00:0');
    });

    it('edits on blur and rewrites the text as hh:mm:ss', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('5:30');
        blur();

        expect(field.control.value).toBe(330);
        expect(field.value).toBe(330);
        expect(input().value).toBe('00:05:30');
    });

    it('edits on Enter without submitting the form', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('900');
        const event = pressEnter();

        expect(field.control.value).toBe(900);
        expect(input().value).toBe('00:15:00');
        expect(event.defaultPrevented).toBe(true);
    });

    it('edits nothing when the input is left without typing', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        blur();
        pressEnter();

        expect(field.control.dirty).toBe(false);
        expect(field.value).toBeUndefined();
    });

    it('keeps typed text it cannot read, says how to write it, and leaves the timeout as it was', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('10 min');
        blur();

        expect(field.control.value).toBe(600);
        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('10 min');
        expect(message('error')).toBe(UNREADABLE_DURATION_MESSAGE);
        expect(input().getAttribute('aria-invalid')).toBe('true');
    });

    it('drops the format error once a readable timeout is entered', () => {
        render(new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS));
        type('00:61:00');
        blur();
        expect(message('error')).toBe(UNREADABLE_DURATION_MESSAGE);

        type('00:20:00');
        pressEnter();

        expect(message('error')).toBeNull();
        expect(input().getAttribute('aria-invalid')).toBe('false');
    });

    it('says the timeout is below the minimum, and marks the input invalid', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('00:00:03');
        blur();

        expect(field.control.value).toBe(3);
        expect(field.control.invalid).toBe(true);
        expect(message('error')).toBe('Must be at least 5 s.');
        expect(input().getAttribute('aria-invalid')).toBe('true');
        expect(input().value).toBe('00:00:03');
    });

    it('names the range in its tooltip', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(tooltipText()).toContain('(5 s to 1 h)');
    });

    it('names only the minimum in its tooltip when there is no maximum', () => {
        render(new ExecutionTimeoutFormField(90, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null }));

        expect(tooltipText()).toContain('(at least 5 s)');
    });

    it('shows no message for a timeout within the limits', () => {
        render(new ExecutionTimeoutFormField(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds!, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(message('error')).toBeNull();
        expect(message('warning')).toBeNull();
    });

    it('warns that a stored timeout above the maximum runs for the maximum, without an error', () => {
        const field = new ExecutionTimeoutFormField(7200, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        expect(input().value).toBe('02:00:00');
        expect(field.control.valid).toBe(true);
        expect(message('warning')).toBe('Runs for at most 1 h, the current limit.');
        expect(message('error')).toBeNull();
    });

    it('caps an edit above the maximum at the maximum, and shows the capped value', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('05:00:00');
        blur();

        expect(field.control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(input().value).toBe('01:00:00');
        expect(message('warning')).toBeNull();
    });

    it('rewrites the typed text even when the capped total equals the one before', () => {
        const field = new ExecutionTimeoutFormField(
            TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds!,
            TEST_EXECUTION_TIMEOUT_LIMITS
        );
        render(field);

        type('03:00:00');
        blur();

        expect(field.control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(input().value).toBe('01:00:00');
    });

    it('caps a huge edit at what the backend can store when there is no maximum', () => {
        const field = new ExecutionTimeoutFormField(60, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null });
        render(field);

        type('9999999:00:00');
        blur();

        expect(field.control.value).toBe(MAX_STORABLE_SECONDS);
    });

    it('follows a value set on the control from outside, dropping a format error', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        type('nonsense');
        blur();

        field.control.setValue(3661);
        fixture.detectChanges();

        expect(input().value).toBe('01:01:01');
        expect(message('error')).toBeNull();
    });

    it('disables the input while the flow is read-only, and follows it', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        expect(input().disabled).toBe(false);

        isReadOnly.set(true);
        fixture.detectChanges();

        expect(input().disabled).toBe(true);
    });
});
