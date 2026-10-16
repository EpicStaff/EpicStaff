import { Component, computed, effect, inject, input, linkedSignal, signal } from '@angular/core';
import { TooltipComponent } from '@shared/components';

import { FlowReadOnlyService } from '../../../../services/flow-readonly.service';
import { formatClockDuration, formatDuration, maskClockDuration, readClockDuration } from '../../../../utils/duration';
import {
    executionTimeoutMinimumRule,
    isValidExecutionTimeout,
} from '../../../../utils/validation/execution-timeout.validator';
import { ExecutionTimeoutFormField } from './execution-timeout-form-field';

/**
 * The most digits the input takes: `99999:99:99` (about 100 000 hours) is below `MAX_STORABLE_SECONDS`, one more
 * digit could pass it.
 */
export const MAX_EXECUTION_TIMEOUT_DIGITS = 9;

export const EXECUTION_TIMEOUT_INPUT_HINT = 'Type digits; they fill in from the right.';

let nextFieldId = 0;

/**
 * The execution timeout of one python code in one masked `hh:mm:ss` input, kept in the control as total seconds.
 * Only digits count, filled from the right like a microwave timer, so the input never holds anything but a
 * duration. The control follows the displayed value on every keystroke, so it is current however the panel closes
 * (Esc, switching nodes) even before the input blurs; an edit capped at the maximum is shown capped at once. Minutes
 * or seconds typed above 59 (`00:00:90`) count as they read, and are normalized (`00:01:30`) on blur and Enter.
 */
@Component({
    selector: 'app-execution-timeout-field',
    imports: [TooltipComponent],
    templateUrl: './execution-timeout-field.component.html',
    styleUrls: ['./execution-timeout-field.component.scss'],
})
export class ExecutionTimeoutFieldComponent {
    public readonly field = input.required<ExecutionTimeoutFormField>();

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
                : `${formatDuration(minSeconds)} to ${formatDuration(maxSeconds)}`;
        return `How long one run of this code may take before it is stopped (${range}). Installing its libraries does not count. ${EXECUTION_TIMEOUT_INPUT_HINT}`;
    });
    protected readonly errorMessage = computed(() => {
        const { minSeconds } = this.field().limits;
        return this.isTyping() || isValidExecutionTimeout(this.totalSeconds(), minSeconds)
            ? ''
            : `Must be ${executionTimeoutMinimumRule(minSeconds)}.`;
    });
    protected readonly aboveMaximumWarning = computed(() => {
        const { maxSeconds } = this.field().limits;
        return maxSeconds !== null && this.totalSeconds() > maxSeconds
            ? `Runs for at most ${formatDuration(maxSeconds)}, the current limit.`
            : '';
    });
    protected readonly hint = EXECUTION_TIMEOUT_INPUT_HINT;
    protected readonly hintId = `execution-timeout-hint-${nextFieldId}`;
    protected readonly messageId = `execution-timeout-message-${nextFieldId++}`;

    protected readonly isReadOnly = inject(FlowReadOnlyService).isReadOnly;

    constructor() {
        effect((onCleanup) => {
            const { control } = this.field();
            this.totalSeconds.set(control.value);
            const subscription = control.valueChanges.subscribe((value) => this.totalSeconds.set(value));
            onCleanup(() => subscription.unsubscribe());
        });
    }

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

    /** On blur and Enter: shows the below-minimum error, and normalizes the text (`00:00:90` → `00:01:30`). */
    protected commit(): void {
        this.isTyping.set(false);
        this.text.set(formatClockDuration(this.field().control.value));
    }
}
