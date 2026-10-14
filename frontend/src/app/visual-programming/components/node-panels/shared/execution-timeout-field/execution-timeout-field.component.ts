import { Component, computed, input } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { InputNumberComponent, ValidationErrorsComponent } from '@shared/components';

import { MIN_EXECUTION_TIMEOUT_MINUTES } from '../../../../core/constants/execution-timeout';
import { ExecutionTimeoutFormField } from './execution-timeout-control';

/** A node's execution timeout in minutes, bounded by the sandbox ceiling. Create the field with `createExecutionTimeoutField`. */
@Component({
    selector: 'app-execution-timeout-field',
    imports: [ReactiveFormsModule, InputNumberComponent, ValidationErrorsComponent],
    templateUrl: './execution-timeout-field.component.html',
    styleUrls: ['./execution-timeout-field.component.scss'],
})
export class ExecutionTimeoutFieldComponent {
    public readonly field = input.required<ExecutionTimeoutFormField>();
    /** For a node that runs its code several times per node run: which runs the limit applies to. */
    public readonly perExecutionNote = input<string>('');

    protected readonly tooltipText = computed(() => {
        const limit = `How long one execution of this node's code may run before the sandbox stops it, in minutes (${MIN_EXECUTION_TIMEOUT_MINUTES} to ${this.field().maxMinutes}).`;
        const note = this.perExecutionNote();
        return note ? `${limit} ${note}` : limit;
    });
    protected readonly aboveCeilingWarning = computed(
        () => `Will be saved as ${this.field().maxMinutes} min, the current limit.`
    );

    protected readonly minMinutes = MIN_EXECUTION_TIMEOUT_MINUTES;

    /**
     * The input's upper bound: the ceiling, which stops its stepper there. Left out while the value is above it
     * (a timeout saved under a higher ceiling), as the input shows a value beyond its bound as an error; the
     * value is valid and gets a warning instead.
     */
    protected inputMax(): number | null {
        const { control, maxMinutes } = this.field();
        return control.value != null && control.value > maxMinutes ? null : maxMinutes;
    }
}
