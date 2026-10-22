import { DebugElement } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { TEST_EXECUTION_TIMEOUT_LIMITS } from '../../services/execution-timeout-limits/execution-timeout-limits.testing';
import { TooltipComponent } from '../tooltip/tooltip.component';
import {
    EXECUTION_TIMEOUT_INPUT_HINT,
    EXECUTION_TIMEOUT_STEP_SECONDS,
    ExecutionTimeoutFieldComponent,
} from './execution-timeout-field.component';
import { ExecutionTimeoutFormField } from './execution-timeout-form-field';

describe('ExecutionTimeoutFieldComponent', () => {
    const NO_MAXIMUM = { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null };
    const THIRTY_MINUTES_MAXIMUM = { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: 1800 };
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

    function caret(): number | null {
        return input().selectionStart;
    }

    function select(start: number, end = start): void {
        input().setSelectionRange(start, end);
    }

    /** An edit as the browser announces it before making it; the field makes it itself. */
    function beforeInput(inputType: string, data: string | null = null, clipboard?: string): InputEvent {
        const event = new InputEvent('beforeinput', { inputType, data, cancelable: true });
        if (clipboard !== undefined) {
            Object.defineProperty(event, 'dataTransfer', { value: { getData: () => clipboard } });
        }
        input().dispatchEvent(event);
        fixture.detectChanges();
        return event;
    }

    /** Types each key at the caret. */
    function typeKeys(keys: string): void {
        for (const key of keys) beforeInput('insertText', key);
    }

    function backspace(): void {
        beforeInput('deleteContentBackward');
    }

    function pressDelete(): void {
        beforeInput('deleteContentForward');
    }

    function paste(text: string): void {
        beforeInput('insertFromPaste', null, text);
    }

    function pressKey(key: string): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key, cancelable: true });
        input().dispatchEvent(event);
        fixture.detectChanges();
        return event;
    }

    /** Text written without `beforeinput`, as autofill or a script does. */
    function replaceText(text: string): void {
        input().value = text;
        input().dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    /** What the mirror under the input draws, with `_` for each slot not typed yet. */
    function drawn(): string {
        const cells = (fixture.nativeElement as HTMLElement).querySelectorAll('.execution-timeout__mirror > span');
        return [...cells]
            .map((cell) => (cell.classList.contains('execution-timeout__cell--untyped') ? '_' : cell.textContent))
            .join('');
    }

    function blur(): void {
        input().dispatchEvent(new Event('blur'));
        fixture.detectChanges();
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

    function tooltipElement(): DebugElement {
        return fixture.debugElement.query(By.directive(TooltipComponent));
    }

    function tooltipText(): string {
        return (tooltipElement().componentInstance as TooltipComponent).tooltipText();
    }

    function visibleLabel(): string | undefined {
        return (tooltipElement().nativeElement as HTMLElement)
            .querySelector('.tooltip-label-text')
            ?.textContent?.trim();
    }

    it('shows the timeout as hh:mm:ss in one numeric input', () => {
        render(new ExecutionTimeoutFormField(3725, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect((fixture.nativeElement as HTMLElement).querySelectorAll('input')).toHaveLength(1);
        expect(input().value).toBe('01:02:05');
        expect(input().getAttribute('inputmode')).toBe('numeric');
    });

    it('draws every digit of a value as typed, and the colons dimmed', () => {
        render(new ExecutionTimeoutFormField(3725, TEST_EXECUTION_TIMEOUT_LIMITS));
        const separators = (fixture.nativeElement as HTMLElement).querySelectorAll(
            '.execution-timeout__cell--separator'
        );

        expect(drawn()).toBe('01:02:05');
        expect([...separators].map((cell) => cell.textContent)).toEqual([':', ':']);
    });

    it('shows the default for a code without a timeout', () => {
        render(new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(input().value).toBe('00:02:00');
    });

    it('shows hours past 99 in full when there is no maximum', () => {
        render(new ExecutionTimeoutFormField(100 * 3600, NO_MAXIMUM));

        expect(input().value).toBe('100:00:00');
        expect(drawn()).toBe('100:00:00');
    });

    it('replaces a stored timeout past 99:59:59 whole when typed into, from the first slot', () => {
        const field = new ExecutionTimeoutFormField(100 * 3600, NO_MAXIMUM);
        render(field);
        select(5);

        typeKeys('1');

        expect(drawn()).toBe('1_:__:__');
        expect(field.control.value).toBe(10 * 3600);
        expect(caret()).toBe(1);
    });

    it('keeps a stored timeout past 99:59:59 on Backspace and Delete', () => {
        const field = new ExecutionTimeoutFormField(100 * 3600, NO_MAXIMUM);
        render(field);

        select(9);
        backspace();
        select(0);
        pressDelete();

        expect(input().value).toBe('100:00:00');
        expect(field.control.value).toBe(100 * 3600);
        expect(field.control.dirty).toBe(false);
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

    it('hides the mirror the input text is drawn by from screen readers', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(
            (fixture.nativeElement as HTMLElement)
                .querySelector('.execution-timeout__mirror')!
                .getAttribute('aria-hidden')
        ).toBe('true');
    });

    it('says in its tooltip only that the code is stopped past the timeout, leaving how to type to screen readers', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(tooltipText()).toBe('Code is stopped if it runs longer than this (5 seconds to 1 hour).');
        expect(tooltipText()).not.toContain(EXECUTION_TIMEOUT_INPUT_HINT);
    });

    it('gives every field its own message id', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));
        const firstId = input().getAttribute('aria-describedby');

        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(input().getAttribute('aria-describedby')).not.toBe(firstId);
    });

    it('overwrites the digit at the caret, moves on to the next slot past colons, and edits the control each time', () => {
        const field = new ExecutionTimeoutFormField(600, NO_MAXIMUM);
        render(field);
        select(3);
        const shown: string[] = [];
        const carets: (number | null)[] = [];
        const values: number[] = [];

        for (const digit of '304') {
            typeKeys(digit);
            shown.push(input().value);
            carets.push(caret());
            values.push(field.control.value);
        }

        expect(shown).toEqual(['00:30:00', '00:30:00', '00:30:40']);
        expect(carets).toEqual([4, 6, 7]);
        expect(values).toEqual([1800, 1800, 1840]);
        expect(field.value).toBe(1840);
    });

    it('keeps the caret where the user put it, editing only the digit there', () => {
        const field = new ExecutionTimeoutFormField(300, NO_MAXIMUM);
        render(field);
        select(3);

        typeKeys('5');

        expect(input().value).toBe('00:55:00');
        expect(field.control.value).toBe(55 * 60);
        expect(caret()).toBe(4);
    });

    it('rejects 6 to 9 in the tens of minutes and of seconds, and any non-digit, keeping the text and caret', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        for (const [position, key] of [
            [3, '6'],
            [6, '9'],
            [0, 'x'],
        ] as const) {
            select(position);
            const event = beforeInput('insertText', key);

            expect(event.defaultPrevented).toBe(true);
            expect(input().value).toBe('00:10:00');
            expect(caret()).toBe(position);
        }
        expect(field.control.dirty).toBe(false);
    });

    it('takes 6 to 9 in the units of minutes and of seconds', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(4);

        typeKeys('9');
        select(7);
        typeKeys('7');

        expect(input().value).toBe('00:19:07');
        expect(field.control.value).toBe(19 * 60 + 7);
    });

    it('leaves an edit it cannot cancel to the browser, then reads it once from the input', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(7, 8);
        const event = new InputEvent('beforeinput', { inputType: 'insertText', data: '5', cancelable: false });

        input().dispatchEvent(event);
        fixture.detectChanges();

        expect(input().value).toBe('00:10:00');
        expect(field.control.dirty).toBe(false);

        // What the browser then writes: the selected last digit replaced by `5`.
        replaceText('00:10:05');

        expect(input().value).toBe('00:10:05');
        expect(field.control.value).toBe(605);
    });

    it('makes a non-cancelable digit the field way, at the caret it was typed at, once the browser inserted it', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(3);

        input().dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertText', data: '5' }));
        // The browser inserts the digit, as it could not be cancelled.
        input().value = '00:510:00';
        input().dispatchEvent(new InputEvent('input', { inputType: 'insertText', data: '5' }));
        fixture.detectChanges();

        expect(input().value).toBe('00:50:00');
        expect(field.control.value).toBe(50 * 60);
        expect(caret()).toBe(4);
    });

    it('makes a non-cancelable 7 in the tens of minutes change nothing', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(3);

        input().dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertText', data: '7' }));
        input().value = '00:710:00';
        input().dispatchEvent(new InputEvent('input', { inputType: 'insertText', data: '7' }));
        fixture.detectChanges();

        expect(input().value).toBe('00:10:00');
        expect(field.control.value).toBe(600);
        expect(field.control.dirty).toBe(false);
        expect(caret()).toBe(3);
    });

    it('takes no digit past the last slot', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(8);

        const event = beforeInput('insertText', '5');

        expect(event.defaultPrevented).toBe(true);
        expect(input().value).toBe('00:10:00');
        expect(field.control.dirty).toBe(false);
    });

    it('clears every slot when all is selected and a digit typed, drawing the untyped ones dimmed until typed', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(0, 8);

        typeKeys('0');
        expect(drawn()).toBe('0_:__:__');
        expect(input().value).toBe('00:00:00');
        expect(field.control.value).toBe(0);
        expect(caret()).toBe(1);

        typeKeys('0');
        expect(drawn()).toBe('00:__:__');
        expect(caret()).toBe(3);

        typeKeys('15');
        expect(drawn()).toBe('00:15:__');
        expect(field.control.value).toBe(900);

        typeKeys('00');
        expect(drawn()).toBe('00:15:00');
        expect(caret()).toBe(8);
    });

    it('clears the slot before the caret on Backspace, moving the caret onto it past colons', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(4);

        backspace();
        expect(drawn()).toBe('00:_0:00');
        expect(field.control.value).toBe(0);
        expect(caret()).toBe(3);

        backspace();
        expect(drawn()).toBe('0_:_0:00');
        expect(caret()).toBe(1);
    });

    it('clears the slot after the caret on Delete, the caret staying', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(3);

        pressDelete();

        expect(drawn()).toBe('00:_0:00');
        expect(field.control.value).toBe(0);
        expect(caret()).toBe(3);
    });

    it('clears the selected slots on Backspace', () => {
        const field = new ExecutionTimeoutFormField(3725, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(3, 8);

        backspace();

        expect(drawn()).toBe('01:__:__');
        expect(field.control.value).toBe(3600);
        expect(caret()).toBe(3);
    });

    it('changes nothing on Backspace at the start or Delete at the end', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        select(0);
        backspace();
        select(8);
        pressDelete();

        expect(drawn()).toBe('00:10:00');
        expect(field.control.dirty).toBe(false);
    });

    it('moves the caret between slots with the arrows, skipping colons', () => {
        render(new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS));
        select(1);
        const carets: (number | null)[] = [];

        for (const key of ['ArrowRight', 'ArrowRight', 'ArrowLeft', 'ArrowLeft', 'ArrowLeft', 'ArrowLeft']) {
            expect(pressKey(key).defaultPrevented).toBe(true);
            carets.push(caret());
        }

        expect(carets).toEqual([3, 4, 3, 1, 0, 0]);
        select(7);
        pressKey('ArrowRight');
        pressKey('ArrowRight');
        expect(caret()).toBe(8);
    });

    it('pastes digits from the caret on, skipping the other characters', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(3);

        paste('45:30');

        expect(input().value).toBe('00:45:30');
        expect(field.control.value).toBe(45 * 60 + 30);
        expect(caret()).toBe(8);
    });

    it('stops a paste at a digit its slot does not take', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(4);

        paste('27');

        expect(input().value).toBe('00:12:00');
        expect(caret()).toBe(6);
    });

    it('reads a clock pasted over everything as it is', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(0, 8);

        paste('00:30:00');

        expect(input().value).toBe('00:30:00');
        expect(field.control.value).toBe(1800);
    });

    it('reads full-width digits', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(3);

        typeKeys('５');

        expect(input().value).toBe('00:50:00');
        expect(field.control.value).toBe(3000);
    });

    it('leaves the text alone while an input method composes it, and types it where composing began', () => {
        const field = new ExecutionTimeoutFormField(600, NO_MAXIMUM);
        render(field);
        select(0);
        input().dispatchEvent(new CompositionEvent('compositionstart'));

        input().value = '１00:10:00';
        input().dispatchEvent(new InputEvent('input', { isComposing: true }));
        fixture.detectChanges();

        expect(input().value).toBe('１00:10:00');
        expect(field.control.value).toBe(600);

        input().dispatchEvent(new CompositionEvent('compositionend', { data: '１' }));
        fixture.detectChanges();

        expect(input().value).toBe('10:10:00');
        expect(field.control.value).toBe(36_600);
        expect(caret()).toBe(1);
    });

    it('reads the digits of text written without beforeinput from the first slot', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        replaceText('00:05:00');
        expect(input().value).toBe('00:05:00');
        expect(field.control.value).toBe(300);

        replaceText('abc');
        expect(input().value).toBe('00:05:00');
        expect(field.control.value).toBe(300);
    });

    it('edits nothing on a keystroke that leaves the timeout as it was, so a code without one keeps none', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        select(0);
        typeKeys('x');
        select(4);
        typeKeys('2');

        expect(field.value).toBeUndefined();
        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('00:02:00');
    });

    it('edits nothing on a 0 typed over a 0', () => {
        const field = new ExecutionTimeoutFormField(0, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(7);

        typeKeys('0');

        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('00:00:00');
    });

    it('keeps a stored timeout above the maximum on a keystroke that does not change it', () => {
        const field = new ExecutionTimeoutFormField(7200, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        select(0);
        typeKeys('x');
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
        select(0);

        typeKeys('5');

        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('51:00:00');

        blur();

        expect(field.control.dirty).toBe(false);
        expect(input().value).toBe('01:00:00');
    });

    it('shows every slot typed once the input is left', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(0, 8);
        typeKeys('001');
        expect(drawn()).toBe('00:1_:__');

        blur();

        expect(drawn()).toBe('00:10:00');
        expect(field.control.value).toBe(600);
    });

    it('shows every slot typed on Enter without submitting the form', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(0, 8);
        typeKeys('0015');

        const event = pressKey('Enter');

        expect(drawn()).toBe('00:15:00');
        expect(event.defaultPrevented).toBe(true);
    });

    it('edits nothing when the input is left without typing', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);

        blur();
        pressKey('Enter');

        expect(field.control.dirty).toBe(false);
        expect(field.value).toBeUndefined();
        expect(input().value).toBe('00:02:00');
    });

    it('shows an hour digit above the maximum as typed, with its error, while the control holds it capped', () => {
        const field = new ExecutionTimeoutFormField(300, THIRTY_MINUTES_MAXIMUM);
        render(field);
        select(0);

        typeKeys('1');

        expect(input().value).toBe('10:05:00');
        expect(drawn()).toBe('10:05:00');
        expect(message()).toBe("Value can't be more than 30 minutes.");
        expect(input().getAttribute('aria-invalid')).toBe('true');
        expect(field.control.value).toBe(1800);
        expect(field.value).toBe(1800);
        expect(field.control.valid).toBe(true);
    });

    it('shows the capped value, without an error, once an edit above the maximum is committed', () => {
        const field = new ExecutionTimeoutFormField(300, THIRTY_MINUTES_MAXIMUM);
        render(field);
        select(0);
        typeKeys('1');

        blur();

        expect(input().value).toBe('00:30:00');
        expect(message()).toBeNull();
        expect(field.control.value).toBe(1800);

        select(0);
        typeKeys('1');
        pressKey('Enter');

        expect(input().value).toBe('00:30:00');
        expect(message()).toBeNull();
    });

    it('keeps changing the display after a digit above the maximum, back into the limits', () => {
        const field = new ExecutionTimeoutFormField(300, THIRTY_MINUTES_MAXIMUM);
        render(field);
        select(3);

        typeKeys('3');
        expect(input().value).toBe('00:35:00');
        expect(message()).toBe("Value can't be more than 30 minutes.");
        expect(field.control.value).toBe(1800);

        typeKeys('0');
        expect(input().value).toBe('00:30:00');
        expect(message()).toBeNull();
        expect(field.control.value).toBe(1800);

        select(3);
        typeKeys('1');
        expect(input().value).toBe('00:10:00');
        expect(field.control.value).toBe(600);
    });

    it('shows a clock pasted above the maximum as pasted, even when its capped total equals the one before', () => {
        const field = new ExecutionTimeoutFormField(
            TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds!,
            TEST_EXECUTION_TIMEOUT_LIMITS
        );
        render(field);
        select(0, 8);

        paste('03:00:00');

        expect(field.control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(input().value).toBe('03:00:00');
        expect(message()).toBe("Value can't be more than 1 hour.");
    });

    it('says the timeout is below the minimum once the input is left, not while typing', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(0, 8);

        typeKeys('000003');

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
        render(new ExecutionTimeoutFormField(90, NO_MAXIMUM));

        expect(tooltipText()).toBe('Code is stopped if it runs longer than this (at least 5 seconds).');
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
        select(6);
        typeKeys('4');

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

    it('shows every slot typed when a button is pressed', () => {
        const field = new ExecutionTimeoutFormField(600, TEST_EXECUTION_TIMEOUT_LIMITS);
        render(field);
        select(0, 8);
        typeKeys('0015');

        press('Increase');

        expect(drawn()).toBe('00:15:30');
        expect(field.value).toBe(930);
    });

    it('offers increase up to what the backend can store when there is no maximum', () => {
        render(new ExecutionTimeoutFormField(100 * 3600, NO_MAXIMUM));

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

    it('shows the default label above the field', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS));

        expect(visibleLabel()).toBe('Execution timeout');
    });

    it('shows the label the form gives above the field', () => {
        render(new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS), {
            label: 'Post-computation execution timeout',
        });

        expect(visibleLabel()).toBe('Post-computation execution timeout');
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
