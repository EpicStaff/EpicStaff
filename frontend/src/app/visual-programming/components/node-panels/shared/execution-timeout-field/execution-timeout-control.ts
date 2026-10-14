import { FormControl, ValidatorFn, Validators } from '@angular/forms';

import { isValidExecutionTimeout, MIN_EXECUTION_TIMEOUT_MINUTES } from '../../../../core/constants/execution-timeout';

/**
 * A node's execution timeout in a panel form: the control and the sandbox ceiling, read once when the form is
 * built so the cap, the field's bounds, its warning and its tooltip cannot disagree.
 */
export interface ExecutionTimeoutFormField {
    control: FormControl<number | null>;
    maxMinutes: number;
}

/** Valid as `isValidExecutionTimeout` says; the error names what is wrong, for the message under the field. */
const executionTimeoutValidator: ValidatorFn = ({ value }) => {
    if (value == null || isValidExecutionTimeout(value)) return null;
    return value < MIN_EXECUTION_TIMEOUT_MINUTES
        ? { min: { min: MIN_EXECUTION_TIMEOUT_MINUTES, actual: value } }
        : { wholeNumber: true };
};

/**
 * The form field of a node's execution timeout, in whole minutes of at least 1.
 *
 * - A node without a stored timeout (from a version saved before nodes had one) starts at the ceiling, which is
 *   what the backend applies to it.
 * - A stored timeout above the ceiling (the ceiling was lowered after the node was saved) is kept and stays
 *   valid: the backend saves it as the ceiling. The field shows a warning for it instead of an error, so it
 *   never stops the panel or the flow from being saved.
 * - An edit cannot go above the ceiling: any change of the value is capped at it.
 */
export function createExecutionTimeoutField(
    storedMinutes: number | null,
    maxMinutes: number
): ExecutionTimeoutFormField {
    const control = new FormControl<number | null>(storedMinutes ?? maxMinutes, [
        Validators.required,
        executionTimeoutValidator,
    ]);
    // The subscription lives as long as the control it listens to; nothing outlives the form.
    control.valueChanges.subscribe((minutes) => {
        if (minutes != null && minutes > maxMinutes) control.setValue(maxMinutes);
    });
    return { control, maxMinutes };
}
