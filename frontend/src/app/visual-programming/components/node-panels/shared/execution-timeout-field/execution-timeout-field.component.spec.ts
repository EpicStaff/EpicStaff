import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { TooltipComponent } from '@shared/components';

import { FlowReadOnlyService } from '../../../../services/flow-readonly.service';
import { readClockDuration } from '../../../../utils/duration';
import { TEST_EXECUTION_TIMEOUT_LIMITS } from '../../../../utils/testing/execution-timeout-limits.testing';
import {
    EXECUTION_TIMEOUT_INPUT_HINT,
    ExecutionTimeoutFieldComponent,
    MAX_EXECUTION_TIMEOUT_DIGITS,
} from './execution-timeout-field.component';
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

    /** Replaces the whole text, as select-all and typing, or select-all and pasting, does. */
    function type(text: string): void {
        input().value = text;
        input().dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    /** Types `characters` at the end of the text. */
    function typeAtEnd(characters: string): void {
        type(input().value + characters);
    }

    /** Deletes the last character of the text. */
    function backspace(): void {
        type(input().value.slice(0, -1));
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

    it('shows the timeout as hh:mm:ss in one numeric input', () => {
        render(new ExecutionTimeoutFormField(3725, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect((fixture.nativeElement as HTMLElement).querySelectorAll('input')).toHaveLength(1);
        expect(input().value).toBe('01:02:05');
        expect(input().getAttribute('inputmode')).toBe('numeric');
    });

    it('shows the default for a code without a timeout', () => {
        render(new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(input().value).toBe('00:02:00');
    });

    it('shows hours past 99 in full when there is no maximum', () => {
        render(new ExecutionTimeoutFormField(100 * 3600, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null }));

        expect(input().value).toBe('100:00:00');
    });

    it('names the input, describes it by how to type and by its message, and announces the message', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        const host = fixture.nativeElement as HTMLElement;

        expect(input().getAttribute('aria-label')).toContain('Execution timeout');
        const messageRegion = host.querySelector('[aria-live="polite"]');
        expect(messageRegion).not.toBeNull();
        const [hintId, messageId] = input().getAttribute('aria-describedby')!.split(' ');
        expect(messageId).toBe(messageRegion!.id);
        expect(host.querySelector(`#${hintId}`)?.textContent?.trim()).toBe(EXECUTION_TIMEOUT_INPUT_HINT);
        expect(input().getAttribute('aria-invalid')).toBe('false');
    });

    it('says how to type in its tooltip', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(tooltipText()).toContain(EXECUTION_TIMEOUT_INPUT_HINT);
    });

    it('gives every field its own message id', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        const firstId = input().getAttribute('aria-describedby');

        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(input().getAttribute('aria-describedby')).not.toBe(firstId);
    });

    it('shifts each digit typed at the end in from the right, and edits the control on every keystroke', () => {
        const field = new ExecutionTimeoutFormField(0, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null });
        render(field);
        const shown: string[] = [];
        const values: number[] = [];

        for (const digit of '13000') {
            typeAtEnd(digit);
            shown.push(input().value);
            values.push(field.control.value);
        }

        expect(shown).toEqual(['00:00:01', '00:00:13', '00:01:30', '00:13:00', '01:30:00']);
        expect(values).toEqual([1, 13, 90, 780, 5400]);
        expect(field.value).toBe(5400);
        expect(input().selectionStart).toBe('01:30:00'.length);
    });

    it('shifts the digits right on Backspace', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        backspace();

        expect(input().value).toBe('00:01:00');
        expect(field.control.value).toBe(60);
    });

    it('replaces the timeout when all is selected and a digit typed', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('7');

        expect(input().value).toBe('00:00:07');
        expect(field.control.value).toBe(7);
    });

    it('reads a pasted clock as it is', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('00:30:00');

        expect(input().value).toBe('00:30:00');
        expect(field.control.value).toBe(1800);
    });

    it('reads only the digits of pasted text', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('1500');
        expect(input().value).toBe('00:15:00');
        expect(field.control.value).toBe(900);

        type('10 min');
        expect(input().value).toBe('00:00:10');
        expect(field.control.value).toBe(10);
    });

    // The specs below set the text an edit inside the clock leaves, as the browser would, then pin what the mask
    // makes of it: the digits are read in order, and the caret moves to the end.
    it('reads a digit typed inside the clock in its place, and moves the caret to the end', () => {
        const field = new ExecutionTimeoutFormField(600, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null });
        render(field);

        // `00:10:00` with `5` typed after its first digit.
        type('050:10:00');

        expect(input().value).toBe('50:10:00');
        expect(field.control.value).toBe(50 * 3600 + 600);
        expect(input().selectionStart).toBe('50:10:00'.length);
    });

    it('reads the clock left when Delete removes a digit inside it', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        // `00:10:00` with Delete before its `1`.
        type('00:0:00');

        expect(input().value).toBe('00:00:00');
        expect(field.control.value).toBe(0);
    });

    it('reads the clock left when a selection inside it is replaced', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        // `00:10:00` with its `10` selected and `2` typed.
        type('00:2:00');

        expect(input().value).toBe('00:02:00');
        expect(field.control.value).toBe(120);
    });

    it('reads full-width digits', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('１５００');

        expect(input().value).toBe('00:15:00');
        expect(field.control.value).toBe(900);
    });

    it('leaves the text alone while an input method composes it, and masks it once composed', () => {
        const field = new ExecutionTimeoutFormField(600, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null });
        render(field);

        input().value = '00:10:00１';
        input().dispatchEvent(new InputEvent('input', { isComposing: true }));
        fixture.detectChanges();

        expect(input().value).toBe('00:10:00１');
        expect(field.control.value).toBe(600);

        input().dispatchEvent(new CompositionEvent('compositionend'));
        fixture.detectChanges();

        expect(input().value).toBe('01:00:01');
        expect(field.control.value).toBe(3601);
    });

    it('edits nothing on a keystroke that leaves the timeout as it was, so a code without one keeps none', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        typeAtEnd('x');
        type('00:02:00');

        expect(field.value).toBeUndefined();
        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('00:02:00');
    });

    it('edits nothing on a 0 typed into 00:00:00', () => {
        const field = new ExecutionTimeoutFormField(0, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        typeAtEnd('0');

        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('00:00:00');
    });

    it('keeps a stored timeout above the maximum on a keystroke that does not change it', () => {
        const field = new ExecutionTimeoutFormField(7200, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        typeAtEnd('x');
        blur();

        expect(field.control.value).toBe(7200);
        expect(field.value).toBe(7200);
        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('02:00:00');
        expect(message('warning')).toBe('Runs for at most 1 h, the current limit.');
    });

    it('edits nothing on a digit typed at the maximum', () => {
        const field = new ExecutionTimeoutFormField(
            TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds!,
            TEST_EXECUTION_TIMEOUT_LIMITS
        );
        render(field);

        typeAtEnd('5');

        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('01:00:00');
    });

    it('drops a letter typed at the end, keeping the timeout', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        typeAtEnd('x');

        expect(input().value).toBe('00:10:00');
        expect(field.control.value).toBe(600);
    });

    it('counts seconds above 59 at once, and normalizes them on blur', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('90');

        expect(input().value).toBe('00:00:90');
        expect(field.control.value).toBe(90);

        blur();

        expect(input().value).toBe('00:01:30');
        expect(field.control.value).toBe(90);
    });

    it('normalizes on Enter without submitting the form', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('0090');
        const event = pressEnter();

        expect(input().value).toBe('00:01:30');
        expect(event.defaultPrevented).toBe(true);
    });

    it('edits nothing when the input is left without typing', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        blur();
        pressEnter();

        expect(field.control.dirty).toBe(false);
        expect(field.value).toBeUndefined();
        expect(input().value).toBe('00:02:00');
    });

    it('caps an edit above the maximum at once, and shows the capped value right away', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        typeAtEnd('0');
        expect(input().value).toBe('01:00:00');

        typeAtEnd('5');

        expect(field.control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(input().value).toBe('01:00:00');
        expect(message('warning')).toBeNull();
    });

    it('shows the capped value even when the capped total equals the one before', () => {
        const field = new ExecutionTimeoutFormField(
            TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds!,
            TEST_EXECUTION_TIMEOUT_LIMITS
        );
        render(field);

        type('03:00:00');

        expect(field.control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(input().value).toBe('01:00:00');
    });

    it('takes no more digits than keep the timeout storable when there is no maximum', () => {
        const field = new ExecutionTimeoutFormField(60, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null });
        render(field);

        type('9'.repeat(MAX_EXECUTION_TIMEOUT_DIGITS + 3));

        expect(input().value).toBe('99999:99:99');
        expect(field.control.value).toBe(readClockDuration('99999:99:99'));
        expect(field.control.value).toBeLessThanOrEqual(MAX_STORABLE_SECONDS);
    });

    it('says the timeout is below the minimum once the input is left, not while typing', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        type('3');

        expect(field.control.value).toBe(3);
        expect(field.control.invalid).toBe(true);
        expect(message('error')).toBeNull();
        expect(input().getAttribute('aria-invalid')).toBe('false');

        blur();

        expect(message('error')).toBe('Must be at least 5 s.');
        expect(input().getAttribute('aria-invalid')).toBe('true');
        expect(input().value).toBe('00:00:03');
    });

    it('says a stored timeout is below the minimum without the input being touched', () => {
        render(new ExecutionTimeoutFormField(3, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(message('error')).toBe('Must be at least 5 s.');
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

    it('rewrites the text for a value set on the control from outside', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        type('45');

        field.control.setValue(3661);
        fixture.detectChanges();

        expect(input().value).toBe('01:01:01');
    });

    it('disables the input while the flow is read-only, and follows it', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        expect(input().disabled).toBe(false);

        isReadOnly.set(true);
        fixture.detectChanges();

        expect(input().disabled).toBe(true);
    });
});
