import { Component, computed, effect, input, linkedSignal, signal } from '@angular/core';

import {
    executionTimeoutMinimumRule,
    isValidExecutionTimeout,
} from '../../form-validators/execution-timeout.validator';
import { formatClockDuration, formatDurationInWords, readClockDuration, readDigits } from '../../utils/duration.util';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from '../tooltip/tooltip.component';
import { ExecutionTimeoutFormField } from './execution-timeout-form-field';

/** How far one press of `−` or `+` moves the timeout. */
export const EXECUTION_TIMEOUT_STEP_SECONDS = 30;

export const EXECUTION_TIMEOUT_DEFAULT_LABEL = 'Execution timeout';

export const EXECUTION_TIMEOUT_INPUT_HINT = 'Type digits; each one replaces the digit after the cursor.';

/** Where the six digit slots of `hh:mm:ss` sit in its text. */
const SLOT_POSITIONS = [0, 1, 3, 4, 6, 7];
const SLOT_POSITIONS_FROM_END = [...SLOT_POSITIONS].reverse();
/** The tens of minutes and of seconds: they take only `0`–`5`. */
const TENS_POSITIONS = new Set([3, 6]);
const CLOCK_LENGTH = 8;
/** A slot not typed yet: counted and shown as a dimmed `0`. */
const UNTYPED = ' ';
const EMPTY_CLOCK = '  :  :  ';

let nextFieldId = 0;

interface ClockEdit {
    clock: string;
    caret: number;
}

/** An edit as `beforeinput` announces it, with the selection it was made on. */
interface PendingEdit {
    inputType: string;
    start: number | null;
    end: number | null;
    data: string;
}

interface ClockCell {
    character: string;
    untyped: boolean;
    separator: boolean;
}

/**
 * The execution timeout of one python code in one masked `hh:mm:ss` input between `−` and `+` buttons, kept in the
 * control as total seconds. Typing overwrites the digit slot at the caret and moves on to the next one, skipping the
 * colons; the caret stays where the user puts it. Slots cleared (Backspace, Delete, a typed-over selection) show as a
 * dimmed `0` and count as one until typed. Tens of minutes and of seconds take only `0`–`5`; any other key changes
 * nothing. The input text itself is transparent: a mirror under it draws each slot in its own color.
 *
 * The control follows the displayed value on every edit and button press, so it is current however the form closes
 * (Esc, switching nodes) even before the input blurs. An edit above the maximum reaches the control capped, but is
 * shown as typed, with its error, until the input is left.
 *
 * Usable in any form: the caller decides when it is read-only, and may add a hint shown under it.
 */
@Component({
    selector: 'app-execution-timeout-field',
    imports: [AppSvgIconComponent, TooltipComponent],
    templateUrl: './execution-timeout-field.component.html',
    styleUrls: ['./execution-timeout-field.component.scss'],
})
export class ExecutionTimeoutFieldComponent {
    public readonly field = input.required<ExecutionTimeoutFormField>();
    /** Disables the input and both buttons. */
    public readonly readonly = input(false);
    /** Shown under the field, and read with it by screen readers. */
    public readonly hint = input('');
    /** Names the input and its buttons for screen readers; tells apart several timeouts in one form. */
    public readonly label = input(EXECUTION_TIMEOUT_DEFAULT_LABEL);

    private readonly totalSeconds = signal(0);
    /** Whether the user typed since leaving the input (blur, Enter): the below-minimum error waits until then. */
    private readonly isTyping = signal(false);

    /**
     * The clock being typed (an untyped slot is a space) while it reads as the control's value, else the value as
     * `hh:mm:ss`. A stored value past `99:59:59` (possible without a maximum) shows every hour digit.
     */
    private readonly clock = linkedSignal<number, string>({
        source: this.totalSeconds,
        computation: (seconds, previous) => {
            if (previous === undefined) return formatClockDuration(seconds);
            // A typed clock above the maximum stays as typed while the control holds it capped, until committed.
            const typedSeconds = readClockDuration(fillUntyped(previous.value));
            return typedSeconds === seconds || this.field().capped(typedSeconds) === seconds
                ? previous.value
                : formatClockDuration(seconds);
        },
    });

    /** The text in the input. */
    protected readonly text = computed(() => fillUntyped(this.clock()));
    /** The seconds the input shows: above the control's while a typed clock above the maximum is not committed. */
    private readonly shownSeconds = computed(() => readClockDuration(this.text()));
    /** The characters the mirror draws under the transparent input text. */
    protected readonly cells = computed<ClockCell[]>(() =>
        [...this.clock()].map((character) => ({
            character: character === UNTYPED ? '0' : character,
            untyped: character === UNTYPED,
            separator: character === ':',
        }))
    );
    protected readonly tooltipText = computed(() => {
        const { minSeconds, maxSeconds } = this.field().limits;
        const range =
            maxSeconds === null
                ? executionTimeoutMinimumRule(minSeconds)
                : `${formatDurationInWords(minSeconds)} to ${formatDurationInWords(maxSeconds)}`;
        return `Code is stopped if it runs longer than this (${range}).`;
    });
    /**
     * Below the minimum (once the input is left), or shown above the maximum (at once). Only the first makes the
     * control invalid: a stored timeout above a lowered maximum stays valid, as the backend saves it as the maximum,
     * and a typed one is kept capped, so an invalid form does not drop the other edits of the form it sits in.
     */
    protected readonly errorMessage = computed(() => {
        const { minSeconds, maxSeconds } = this.field().limits;
        if (!this.isTyping() && !isValidExecutionTimeout(this.totalSeconds(), minSeconds)) {
            return `Value can't be less than ${formatDurationInWords(minSeconds)}.`;
        }
        if (maxSeconds !== null && this.shownSeconds() > maxSeconds) {
            return `Value can't be more than ${formatDurationInWords(maxSeconds)}.`;
        }
        return '';
    });
    /**
     * Whether a step button would move the timeout. A button at a limit stays enabled and only says it is unavailable
     * (`aria-disabled`): disabling it natively would drop the keyboard focus the press that reached the limit left on it.
     */
    protected readonly canDecrease = computed(() => this.totalSeconds() > this.field().limits.minSeconds);
    protected readonly canIncrease = computed(() => this.totalSeconds() < this.field().upperBound);
    protected readonly inputLabel = computed(() => `${this.label()}, hh:mm:ss`);
    protected readonly describedBy = computed(() =>
        [this.typingHintId, this.hint() ? this.hintId : '', this.messageId].filter(Boolean).join(' ')
    );

    /** Follows the control of the current field: its value now, and every later change, until the field is replaced. */
    private readonly syncWithControl = effect((onCleanup) => {
        const { control } = this.field();
        this.totalSeconds.set(control.value);
        const subscription = control.valueChanges.subscribe((value) => this.totalSeconds.set(value));
        onCleanup(() => subscription.unsubscribe());
    });

    protected readonly typingHint = EXECUTION_TIMEOUT_INPUT_HINT;
    protected readonly stepSeconds = EXECUTION_TIMEOUT_STEP_SECONDS;
    protected readonly decreaseLabel = `Decrease by ${EXECUTION_TIMEOUT_STEP_SECONDS} seconds`;
    protected readonly increaseLabel = `Increase by ${EXECUTION_TIMEOUT_STEP_SECONDS} seconds`;
    protected readonly typingHintId = `execution-timeout-typing-hint-${nextFieldId}`;
    protected readonly hintId = `execution-timeout-hint-${nextFieldId}`;
    protected readonly messageId = `execution-timeout-message-${nextFieldId++}`;

    /** The selection when an input method started composing: its text goes there once composed. */
    private compositionRange: [number, number] = [0, 0];
    /** A non-cancelable edit, from its `beforeinput` until the browser has made it (`input`). */
    private pendingEdit: PendingEdit | null = null;

    /**
     * Makes every edit itself (typing, Backspace, Delete, cut, paste, drop) instead of the browser, so a digit
     * overwrites its slot and the caret stays put. Text an input method composes cannot be stopped here: it is
     * applied on `compositionend`. Nor can an edit the browser marks non-cancelable (some on-screen keyboards): it is
     * kept, with the selection it was made on, and made once the browser's own edit reaches `input`.
     */
    protected onBeforeInput(event: InputEvent, input: HTMLInputElement): void {
        if (event.isComposing) return;
        const edit: PendingEdit = {
            inputType: event.inputType,
            start: input.selectionStart,
            end: input.selectionEnd,
            data: event.data ?? event.dataTransfer?.getData('text') ?? '',
        };
        this.pendingEdit = event.cancelable ? null : edit;
        if (!event.cancelable) return;
        event.preventDefault();
        this.makeEdit(edit, input);
    }

    /**
     * An `input` event: replaces the browser's edit of a non-cancelable `beforeinput` with that edit made the
     * field's way. Without one (autofill, a script setting the value) the digits are read from the first slot.
     * Skipped while an input method composes text.
     */
    protected onInputEvent(event: Event, input: HTMLInputElement): void {
        if ((event as InputEvent).isComposing) return;
        const pending = this.pendingEdit;
        this.pendingEdit = null;
        if (pending) {
            this.makeEdit(pending, input);
        } else if (input.value !== this.text()) {
            this.typeAt(0, CLOCK_LENGTH, input.value, input);
        }
    }

    protected onCompositionStart(input: HTMLInputElement): void {
        this.compositionRange = [input.selectionStart ?? 0, input.selectionEnd ?? 0];
    }

    /** Replaces the text the input method left in the input with its digits typed where the composing started. */
    protected onCompositionEnd(event: CompositionEvent, input: HTMLInputElement): void {
        const [start, end] = this.compositionRange;
        this.typeAt(start, end, event.data, input);
    }

    /** ArrowLeft and ArrowRight without a selection: moves the caret to the slot before or after, skipping colons. */
    protected moveCaret(event: Event, forward: boolean, input: HTMLInputElement): void {
        const caret = input.selectionStart ?? 0;
        if (caret !== input.selectionEnd || this.clock().length !== CLOCK_LENGTH) return;
        event.preventDefault();
        const next = forward ? (slotFrom(caret + 1) ?? CLOCK_LENGTH) : (slotBefore(caret) ?? 0);
        input.setSelectionRange(next, next);
    }

    /** `−` and `+`: moves the timeout by `deltaSeconds` within the limits, and shows it as left. */
    protected step(deltaSeconds: number): void {
        if (this.readonly() || !(deltaSeconds < 0 ? this.canDecrease() : this.canIncrease())) return;
        this.field().step(deltaSeconds);
        this.commit();
    }

    /** On blur and Enter: shows the below-minimum error, and the value with every slot typed. */
    protected commit(): void {
        this.isTyping.set(false);
        this.clock.set(formatClockDuration(this.field().control.value));
    }

    /**
     * Makes `edit` on the selection it was announced with. Backspace and Delete leave a value past `99:59:59` alone:
     * it has no slots, and clearing it all would lose it. An edit that changes nothing still drops text the browser
     * already wrote (a non-cancelable edit).
     */
    private makeEdit(edit: PendingEdit, input: HTMLInputElement): void {
        if (!edit.inputType.startsWith('delete')) {
            this.typeAt(edit.start, edit.end, edit.data, input);
            return;
        }
        if (this.clock().length === CLOCK_LENGTH) {
            const { clock, start, end } = this.editRange(edit.start, edit.end);
            this.apply(clearDigits(clock, start, end, edit.inputType.includes('Backward')), input);
        }
        if (input.value !== this.text()) this.show(input, edit.start ?? 0);
    }

    /**
     * Types the digits of `text` over the selection from `start` to `end`. When no digit is taken nothing changes,
     * apart from dropping text the browser already wrote (an input method, autofill).
     */
    private typeAt(start: number | null, end: number | null, text: string, input: HTMLInputElement): void {
        const range = this.editRange(start, end);
        const edit = typeDigits(range.clock, range.start, range.end, text);
        if (edit) {
            this.apply(edit, input);
        } else if (input.value !== this.text()) {
            this.show(input, start ?? 0);
        }
    }

    /** The clock an edit starts from; a value past `99:59:59` has no slots to edit in place, so it is replaced whole. */
    private editRange(start: number | null, end: number | null): { clock: string; start: number; end: number } {
        const clock = this.clock();
        if (clock.length !== CLOCK_LENGTH) return { clock: EMPTY_CLOCK, start: 0, end: CLOCK_LENGTH };
        return { clock, start: start ?? 0, end: end ?? start ?? 0 };
    }

    /**
     * Shows `edit` as typed, and edits the control to match, capped at the maximum: a clock above it is shown, with
     * its error, until committed (blur, Enter), so the next digits can bring it back down. An edit that leaves the
     * timeout as it was (`0` typed over a `0`, a digit past the maximum) edits nothing: a code without a timeout keeps
     * following the default, and a stored one above the maximum stays.
     */
    private apply(edit: ClockEdit | null, input: HTMLInputElement): void {
        if (!edit) return;
        this.isTyping.set(true);
        const field = this.field();
        const typedSeconds = readClockDuration(fillUntyped(edit.clock));
        const currentSeconds = field.control.value;
        if (typedSeconds !== currentSeconds && field.capped(typedSeconds) !== currentSeconds) {
            field.edit(typedSeconds);
        }
        this.clock.set(edit.clock);
        this.show(input, edit.caret);
    }

    /** Writes the text and caret at once: the binding writes only on change detection, and moves the caret to the end. */
    private show(input: HTMLInputElement, caret: number): void {
        input.value = this.text();
        input.setSelectionRange(caret, caret);
    }
}

/**
 * Types the digits of `text` into the slots from `start` on, after clearing the slots from `start` to `end`. Stops at
 * the end of the clock or at a digit its slot does not take (`6`–`9` in a tens slot). Null when no digit is taken.
 */
function typeDigits(clock: string, start: number, end: number, text: string): ClockEdit | null {
    const characters = clearSlots(clock, start, end);
    let caret = start;
    let typed = 0;
    for (const digit of readDigits(text)) {
        const position = slotFrom(caret);
        if (position === undefined || (TENS_POSITIONS.has(position) && digit > '5')) break;
        characters[position] = digit;
        caret = slotFrom(position + 1) ?? CLOCK_LENGTH;
        typed++;
    }
    return typed ? { clock: characters.join(''), caret } : null;
}

/**
 * Clears the selected slots; without a selection the slot before the caret (Backspace, the caret moving onto it) or
 * after it (Delete, the caret staying). Null when there is no such slot.
 */
function clearDigits(clock: string, start: number, end: number, backward: boolean): ClockEdit | null {
    if (start !== end) return { clock: clearSlots(clock, start, end).join(''), caret: start };
    const position = backward ? slotBefore(start) : slotFrom(start);
    if (position === undefined) return null;
    return { clock: clearSlots(clock, position, position + 1).join(''), caret: position };
}

function clearSlots(clock: string, start: number, end: number): string[] {
    const characters = [...clock];
    for (const position of SLOT_POSITIONS) {
        if (position >= start && position < end) characters[position] = UNTYPED;
    }
    return characters;
}

/** The first slot at or after `position`. */
function slotFrom(position: number): number | undefined {
    return SLOT_POSITIONS.find((slot) => slot >= position);
}

/** The last slot before `position`. */
function slotBefore(position: number): number | undefined {
    return SLOT_POSITIONS_FROM_END.find((slot) => slot < position);
}

function fillUntyped(clock: string): string {
    return clock.replaceAll(UNTYPED, '0');
}
