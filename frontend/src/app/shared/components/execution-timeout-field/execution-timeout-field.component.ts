import { Component, computed, effect, input, linkedSignal, signal } from '@angular/core';

import {
    executionTimeoutMinimumRule,
    isValidExecutionTimeout,
} from '../../form-validators/execution-timeout.validator';
import {
    formatClockDuration,
    formatDurationInWords,
    maskClockDuration,
    readClockDuration,
} from '../../utils/duration.util';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from '../tooltip/tooltip.component';
import { ExecutionTimeoutFormField } from './execution-timeout-form-field';

/**
 * The most digits the input takes: `99999:99:99` (about 100 000 hours) is below `MAX_STORABLE_SECONDS`, one more
 * digit could pass it.
 */
export const MAX_EXECUTION_TIMEOUT_DIGITS = 9;

/** How far one press of `−` or `+` moves the timeout. */
export const EXECUTION_TIMEOUT_STEP_SECONDS = 30;

export const EXECUTION_TIMEOUT_DEFAULT_LABEL = 'Execution timeout';

export const EXECUTION_TIMEOUT_INPUT_HINT = 'Type digits; they fill in from the right.';

let nextFieldId = 0;

/**
 * The execution timeout of one python code in one masked `hh:mm:ss` input between `−` and `+` buttons, kept in the
 * control as total seconds. Only digits count, filled from the right like a microwave timer, so the input never holds
 * anything but a duration. The control follows the displayed value on every keystroke and button press, so it is
 * current however the form closes (Esc, switching nodes) even before the input blurs; an edit capped at the maximum
 * is shown capped at once. Minutes or seconds typed above 59 (`00:00:90`) count as they read, and are normalized
 * (`00:01:30`) on blur and Enter.
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

    /** The text in the input: the typed clock while it reads as the control's value, else the value as `hh:mm:ss`. */
    protected readonly text = linkedSignal<number, string>({
        source: this.totalSeconds,
        computation: (seconds, previous) =>
            previous !== undefined && readClockDuration(previous.value) === seconds
                ? previous.value
                : formatClockDuration(seconds),
    });

    protected readonly tooltipText = computed(() => {
        const { minSeconds, maxSeconds } = this.field().limits;
        const range =
            maxSeconds === null
                ? executionTimeoutMinimumRule(minSeconds)
                : `${formatDurationInWords(minSeconds)} to ${formatDurationInWords(maxSeconds)}`;
        return `Code is stopped if it runs longer than this (${range}).`;
    });
    /**
     * Below the minimum (once the input is left), or above the maximum. Only the first makes the control invalid: a
     * stored timeout above a lowered maximum stays valid, as the backend saves it as the maximum, so an invalid form
     * does not drop the other edits of the form it sits in.
     */
    protected readonly errorMessage = computed(() => {
        const { minSeconds, maxSeconds } = this.field().limits;
        const seconds = this.totalSeconds();
        if (!this.isTyping() && !isValidExecutionTimeout(seconds, minSeconds)) {
            return `Value can't be less than ${formatDurationInWords(minSeconds)}.`;
        }
        if (maxSeconds !== null && seconds > maxSeconds) {
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

    /** An `input` event; skipped while an input method composes text, which `compositionend` then masks. */
    protected onInputEvent(event: Event, input: HTMLInputElement): void {
        if ((event as InputEvent).isComposing) return;
        this.onInput(input);
    }

    /**
     * Masks whatever the input now holds (a keystroke, Backspace, a paste) and edits the control to match. A
     * keystroke that leaves the timeout as it was (a letter, `0` into `00:00:00`, a digit past the maximum) edits
     * nothing: a code without a timeout keeps following the default, and a stored one above the maximum stays.
     */
    protected onInput(input: HTMLInputElement): void {
        this.isTyping.set(true);
        const field = this.field();
        const clock = maskClockDuration(input.value, MAX_EXECUTION_TIMEOUT_DIGITS);
        const typedSeconds = readClockDuration(clock);
        const currentSeconds = field.control.value;
        if (typedSeconds !== currentSeconds && field.capped(typedSeconds) !== currentSeconds) {
            field.edit(typedSeconds);
        }
        const shown = field.control.value === typedSeconds ? clock : formatClockDuration(field.control.value);
        this.text.set(shown);
        // Written directly as well: the binding skips a text equal to the one it last wrote, while the input may
        // still show the typed character the mask dropped (a letter, a digit past the limit).
        input.value = shown;
        input.setSelectionRange(shown.length, shown.length);
    }

    /** `−` and `+`: moves the timeout by `deltaSeconds` within the limits, and shows it as left. */
    protected step(deltaSeconds: number): void {
        if (this.readonly() || !(deltaSeconds < 0 ? this.canDecrease() : this.canIncrease())) return;
        this.field().step(deltaSeconds);
        this.commit();
    }

    /** On blur and Enter: shows the below-minimum error, and normalizes the text (`00:00:90` → `00:01:30`). */
    protected commit(): void {
        this.isTyping.set(false);
        this.text.set(formatClockDuration(this.field().control.value));
    }
}
