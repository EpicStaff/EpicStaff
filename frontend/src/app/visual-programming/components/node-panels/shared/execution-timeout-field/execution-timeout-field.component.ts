import { Component, computed, effect, inject, input, signal, viewChild } from '@angular/core';
import { InputNumberComponent, TooltipComponent } from '@shared/components';

import { FlowReadOnlyService } from '../../../../services/flow-readonly.service';
import { formatDuration, joinDuration, splitDuration } from '../../../../utils/duration';
import {
    executionTimeoutMinimumRule,
    isValidExecutionTimeout,
} from '../../../../utils/validation/execution-timeout.validator';
import { ExecutionTimeoutFormField } from './execution-timeout-form-field';

/**
 * The execution timeout of one python code, typed as hours, minutes and seconds and kept in the control as
 * total seconds.
 */
@Component({
    selector: 'app-execution-timeout-field',
    imports: [InputNumberComponent, TooltipComponent],
    templateUrl: './execution-timeout-field.component.html',
    styleUrls: ['./execution-timeout-field.component.scss'],
})
export class ExecutionTimeoutFieldComponent {
    public readonly field = input.required<ExecutionTimeoutFormField>();

    private readonly hoursInput = viewChild.required<InputNumberComponent>('hoursInput');
    private readonly minutesInput = viewChild.required<InputNumberComponent>('minutesInput');
    private readonly secondsInput = viewChild.required<InputNumberComponent>('secondsInput');

    /**
     * Never equal to itself: every edit, even one capped back to the total before it, writes the parts again, so
     * the inputs never keep a typed part the control did not take.
     */
    private readonly totalSeconds = signal(0, { equal: () => false });

    protected readonly tooltipText = computed(() => {
        const { minSeconds, maxSeconds } = this.field().limits;
        const range =
            maxSeconds === null
                ? executionTimeoutMinimumRule(minSeconds)
                : `${formatDuration(minSeconds)} to ${formatDuration(maxSeconds)}`;
        return `How long one run of this code may take before it is stopped (${range}). Installing its libraries does not count.`;
    });
    protected readonly errorMessage = computed(() => {
        const { minSeconds } = this.field().limits;
        return isValidExecutionTimeout(this.totalSeconds(), minSeconds)
            ? ''
            : `Must be ${executionTimeoutMinimumRule(minSeconds)}.`;
    });
    protected readonly aboveMaximumWarning = computed(() => {
        const { maxSeconds } = this.field().limits;
        return maxSeconds !== null && this.totalSeconds() > maxSeconds
            ? `Runs for at most ${formatDuration(maxSeconds)}, the current limit.`
            : '';
    });

    protected readonly isReadOnly = inject(FlowReadOnlyService).isReadOnly;

    constructor() {
        effect((onCleanup) => {
            const { control } = this.field();
            this.totalSeconds.set(control.value);
            const subscription = control.valueChanges.subscribe((value) => this.totalSeconds.set(value));
            onCleanup(() => subscription.unsubscribe());
        });
        // The inputs are written directly rather than bound: a binding skips a part that equals its last bound
        // value, even when the input shows a different one typed since.
        effect(() => {
            const { hours, minutes, seconds } = splitDuration(this.totalSeconds());
            this.hoursInput().value.set(hours);
            this.minutesInput().value.set(minutes);
            this.secondsInput().value.set(seconds);
        });
    }

    protected onPartChange(): void {
        // A pasted fraction would make the total fractional: round it to whole seconds.
        const totalSeconds = joinDuration({
            hours: this.hoursInput().value() ?? 0,
            minutes: this.minutesInput().value() ?? 0,
            seconds: this.secondsInput().value() ?? 0,
        });
        this.field().edit(Math.round(totalSeconds));
    }
}
