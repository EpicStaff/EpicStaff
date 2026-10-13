import { FormControl, Validators } from '@angular/forms';

import { MIN_EXECUTION_TIMEOUT_MINUTES } from '../../../../core/constants/execution-timeout';

/**
 * A node's execution timeout in a panel form: the control and the ceiling it was validated against, read once
 * when the form is built so the validators, the field's bounds and its tooltip cannot disagree.
 */
export interface ExecutionTimeoutFormField {
    control: FormControl<number | null>;
    maxMinutes: number;
}

/**
 * The form field of a node's execution timeout, in whole minutes from 1 to `maxMinutes` (the sandbox ceiling).
 * A node without a stored timeout (from a version saved before nodes had one) starts at the ceiling, which is
 * what the backend applies to it.
 */
export function createExecutionTimeoutField(
    storedMinutes: number | null,
    maxMinutes: number
): ExecutionTimeoutFormField {
    const control = new FormControl<number | null>(storedMinutes ?? maxMinutes, [
        Validators.required,
        Validators.min(MIN_EXECUTION_TIMEOUT_MINUTES),
        Validators.max(maxMinutes),
        (current) => (current.value == null || Number.isInteger(current.value) ? null : { wholeNumber: true }),
    ]);
    // A timeout saved under a higher ceiling than today's is shown invalid on open, not only after an edit.
    if (control.invalid) control.markAsTouched();
    return { control, maxMinutes };
}
