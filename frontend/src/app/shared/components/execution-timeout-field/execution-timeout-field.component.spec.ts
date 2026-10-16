import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { TEST_EXECUTION_TIMEOUT_LIMITS } from '../../services/execution-timeout-limits/execution-timeout-limits.testing';
import { readClockDuration } from '../../utils/duration.util';
import { TooltipComponent } from '../tooltip/tooltip.component';
import {
    EXECUTION_TIMEOUT_INPUT_HINT,
    EXECUTION_TIMEOUT_STEP_SECONDS,
    ExecutionTimeoutFieldComponent,
    MAX_EXECUTION_TIMEOUT_DIGITS,
} from './execution-timeout-field.component';
import { ExecutionTimeoutFormField, MAX_STORABLE_SECONDS } from './execution-timeout-form-field';

describe('ExecutionTimeoutFieldComponent', () => {
    let fixture: ComponentFixture<ExecutionTimeoutFieldComponent>;

    function render(
        field: ExecutionTimeoutFormField,
        inputs: { readonly?: boolean; hint?: string; label?: string } = {}
    ): void {
        fixture = TestBed.createComponent(ExecutionTimeoutFieldComponent);
        fixture.componentRef.setInput('field', field);
        for (const [name, value] of Object.entries(inputs)) {
            fixture.componentRef.setInput(name, value);
        }
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

    function message(): string | null {
        const element = (fixture.nativeElement as HTMLElement).querySelector('.execution-timeout__message');
        return element?.textContent?.trim() ?? null;
    }

    function button(name: 'Decrease' | 'Increase'): HTMLButtonElement {
        const label = `${name} by ${EXECUTION_TIMEOUT_STEP_SECONDS} seconds`;
        return (fixture.nativeElement as HTMLElement).querySelector(`button[aria-label="${label}"]`)!;
    }

    /** Whether the button says it would not move the timeout: at a limit it is marked, not natively disabled. */
    function unavailable(name: 'Decrease' | 'Increase'): boolean {
        return button(name).getAttribute('aria-disabled') === 'true';
    }

    function press(name: 'Decrease' | 'Increase'): void {
        button(name).click();
        fixture.detectChanges();
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
        expect(message()).toBe("Value can't be more than 1 hour.");
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
        expect(message()).toBeNull();
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
        expect(message()).toBeNull();
        expect(input().getAttribute('aria-invalid')).toBe('false');

        blur();

        expect(message()).toBe("Value can't be less than 5 seconds.");
        expect(input().getAttribute('aria-invalid')).toBe('true');
        expect(input().value).toBe('00:00:03');
    });

    it('says a stored timeout is below the minimum without the input being touched', () => {
        render(new ExecutionTimeoutFormField(3, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(message()).toBe("Value can't be less than 5 seconds.");
    });

    it('names the range in its tooltip', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(tooltipText()).toContain('(5 seconds to 1 hour)');
    });

    it('names only the minimum in its tooltip when there is no maximum', () => {
        render(new ExecutionTimeoutFormField(90, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null }));

        expect(tooltipText()).toContain('(at least 5 seconds)');
    });

    it('shows no message for a timeout within the limits', () => {
        render(new ExecutionTimeoutFormField(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds!, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(message()).toBeNull();
        expect(input().getAttribute('aria-invalid')).toBe('false');
    });

    it('says a stored timeout is above the maximum, while the control stays valid', () => {
        const field = new ExecutionTimeoutFormField(7200, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        expect(input().value).toBe('02:00:00');
        expect(message()).toBe("Value can't be more than 1 hour.");
        expect(input().getAttribute('aria-invalid')).toBe('true');
        expect(field.control.valid).toBe(true);
        expect(field.control.dirty).toBe(false);
    });

    it('rewrites the text for a value set on the control from outside', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        type('45');

        field.control.setValue(3661);
        fixture.detectChanges();

        expect(input().value).toBe('01:01:01');
    });

    it('disables the input and both buttons while read-only, and follows it', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        expect(input().disabled).toBe(false);
        expect(button('Decrease').disabled).toBe(false);
        expect(button('Increase').disabled).toBe(false);

        fixture.componentRef.setInput('readonly', true);
        fixture.detectChanges();

        expect(input().disabled).toBe(true);
        expect(button('Decrease').disabled).toBe(true);
        expect(button('Increase').disabled).toBe(true);
    });

    it('steps the timeout by 30 seconds with its buttons, editing the control', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        press('Increase');
        expect(input().value).toBe('00:02:00');
        expect(field.value).toBe(120);
        expect(field.control.dirty).toBe(true);

        press('Decrease');
        press('Decrease');
        expect(input().value).toBe('00:01:00');
        expect(field.value).toBe(60);
    });

    it('names its buttons, and keeps them from submitting the form', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        for (const name of ['Decrease', 'Increase'] as const) {
            expect(button(name)).not.toBeNull();
            expect(button(name).type).toBe('button');
        }
    });

    it('steps down no lower than the minimum, and marks decrease unavailable there', () => {
        const field = new ExecutionTimeoutFormField(20, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        press('Decrease');

        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds);
        expect(input().value).toBe('00:00:05');
        expect(unavailable('Decrease')).toBe(true);
        expect(unavailable('Increase')).toBe(false);
    });

    it('steps up no higher than the maximum, and marks increase unavailable there', () => {
        const field = new ExecutionTimeoutFormField(
            TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds! - 10,
            TEST_EXECUTION_TIMEOUT_LIMITS
        );
        render(field);

        press('Increase');

        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(input().value).toBe('01:00:00');
        expect(unavailable('Increase')).toBe(true);
        expect(unavailable('Decrease')).toBe(false);
    });

    it('marks decrease unavailable for a stored timeout below the minimum, and steps it up into the limits', () => {
        const field = new ExecutionTimeoutFormField(3, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        expect(unavailable('Decrease')).toBe(true);

        press('Increase');

        expect(field.value).toBe(33);
        expect(message()).toBeNull();
    });

    it('steps a stored timeout above the maximum down into the limits, clearing its message', () => {
        const field = new ExecutionTimeoutFormField(7200, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        expect(unavailable('Increase')).toBe(true);

        press('Decrease');

        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(input().value).toBe('01:00:00');
        expect(message()).toBeNull();
    });

    it('normalizes the typed text when a button is pressed', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        type('90');

        press('Increase');

        expect(input().value).toBe('00:02:00');
        expect(field.value).toBe(120);
    });

    it('offers increase up to what the backend can store when there is no maximum', () => {
        render(new ExecutionTimeoutFormField(100 * 3600, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null }));

        expect(unavailable('Increase')).toBe(false);
    });

    it('keeps a button at a limit focusable, so the keyboard focus stays on it, and pressing it changes nothing', () => {
        const field = new ExecutionTimeoutFormField(
            TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds! - 10,
            TEST_EXECUTION_TIMEOUT_LIMITS
        );
        render(field);
        button('Increase').focus();

        press('Increase');

        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(button('Increase').disabled).toBe(false);
        expect(unavailable('Increase')).toBe(true);
        expect(document.activeElement).toBe(button('Increase'));

        press('Increase');

        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
    });

    it('leaves the control untouched when a button at a limit is pressed', () => {
        const field = new ExecutionTimeoutFormField(
            TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds,
            TEST_EXECUTION_TIMEOUT_LIMITS
        );
        render(field);

        press('Decrease');

        expect(field.control.dirty).toBe(false);
        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds);
    });

    it('groups the input and its buttons under the field name', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        const group = (fixture.nativeElement as HTMLElement).querySelector('[role="group"]')!;

        expect(group.getAttribute('aria-label')).toBe('Execution timeout');
        expect(group.contains(input())).toBe(true);
        expect(group.contains(button('Decrease'))).toBe(true);
        expect(group.contains(button('Increase'))).toBe(true);
    });

    it('names the group and the input by the label the form gives', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS), {
            label: 'Pre-computation execution timeout',
        });

        expect((fixture.nativeElement as HTMLElement).querySelector('[role="group"]')!.getAttribute('aria-label')).toBe(
            'Pre-computation execution timeout'
        );
        expect(input().getAttribute('aria-label')).toBe('Pre-computation execution timeout, hh:mm:ss');
    });

    it('shows a hint under the field and describes the input by it', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS), {
            hint: 'Agents stop waiting after their own tool timeout.',
        });
        const host = fixture.nativeElement as HTMLElement;

        const hint = host.querySelector('.execution-timeout__hint');
        expect(hint?.textContent?.trim()).toBe('Agents stop waiting after their own tool timeout.');
        expect(input().getAttribute('aria-describedby')!.split(' ')).toContain(hint!.id);
    });

    it('shows no hint by default', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect((fixture.nativeElement as HTMLElement).querySelector('.execution-timeout__hint')).toBeNull();
        expect(input().getAttribute('aria-describedby')!.split(' ')).toHaveLength(2);
    });
});
