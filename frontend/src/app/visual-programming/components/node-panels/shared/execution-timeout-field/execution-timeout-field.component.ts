import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { TooltipComponent } from '@shared/components';

import { FlowReadOnlyService } from '../../../../services/flow-readonly.service';
import { formatClockDuration, formatDuration, parseDuration } from '../../../../utils/duration';
import {
    executionTimeoutMinimumRule,
    isValidExecutionTimeout,
} from '../../../../utils/validation/execution-timeout.validator';
import { ExecutionTimeoutFormField } from './execution-timeout-form-field';

export const UNREADABLE_DURATION_MESSAGE = 'Use hh:mm:ss, for example 00:10:00.';

let nextFieldId = 0;

/**
 * The execution timeout of one python code, typed as `hh:mm:ss` in one input and kept in the control as total
 * seconds. The text is read on blur and on Enter, not on every keystroke, so a half-typed `00:0` never lands.
 */
@Component({
    selector: 'app-execution-timeout-field',
    imports: [TooltipComponent],
    templateUrl: './execution-timeout-field.component.html',
    styleUrls: ['./execution-timeout-field.component.scss'],
})
export class ExecutionTimeoutFieldComponent {
    public readonly field = input.required<ExecutionTimeoutFormField>();

    /**
     * Never equal to itself: every edit, even one capped back to the total before it, writes the text again, so
     * the input never keeps typed text the control did not take.
     */
    private readonly totalSeconds = signal(0, { equal: () => false });

    protected readonly text = signal('');
    protected readonly isUnreadable = signal(false);

    protected readonly tooltipText = computed(() => {
        const { minSeconds, maxSeconds } = this.field().limits;
        const range =
            maxSeconds === null
                ? executionTimeoutMinimumRule(minSeconds)
                : `${formatDuration(minSeconds)} to ${formatDuration(maxSeconds)}`;
        return `How long one run of this code may take before it is stopped (${range}). Installing its libraries does not count.`;
    });
    protected readonly errorMessage = computed(() => {
        if (this.isUnreadable()) {
            return UNREADABLE_DURATION_MESSAGE;
        }
        const { minSeconds } = this.field().limits;
        return isValidExecutionTimeout(this.totalSeconds(), minSeconds)
            ? ''
            : `Must be ${executionTimeoutMinimumRule(minSeconds)}.`;
    });
    protected readonly aboveMaximumWarning = computed(() => {
        const { maxSeconds } = this.field().limits;
        return !this.errorMessage() && maxSeconds !== null && this.totalSeconds() > maxSeconds
            ? `Runs for at most ${formatDuration(maxSeconds)}, the current limit.`
            : '';
    });
    protected readonly messageId = `execution-timeout-message-${nextFieldId++}`;

    protected readonly isReadOnly = inject(FlowReadOnlyService).isReadOnly;

    /** Whether the text was typed since it was last written: focusing and leaving the input edits nothing. */
    private isTyped = false;

    constructor() {
        effect((onCleanup) => {
            const { control } = this.field();
            this.totalSeconds.set(control.value);
            const subscription = control.valueChanges.subscribe((value) => this.totalSeconds.set(value));
            onCleanup(() => subscription.unsubscribe());
        });
        effect(() => this.writeText(this.totalSeconds()));
    }

    protected onInput(text: string): void {
        this.isTyped = true;
        this.text.set(text);
    }

    protected commit(): void {
        if (!this.isTyped) {
            return;
        }
        const seconds = parseDuration(this.text());
        if (seconds === null) {
            this.isUnreadable.set(true);
            return;
        }
        const field = this.field();
        field.edit(seconds);
        this.writeText(field.control.value);
    }

    private writeText(totalSeconds: number): void {
        this.isTyped = false;
        this.isUnreadable.set(false);
        this.text.set(formatClockDuration(totalSeconds));
    }
}
