import { ValidatorFn } from '@angular/forms';

import { formatDurationInWords } from '../utils/duration.util';

/**
 * Whether `seconds` is an execution timeout a python code may carry: a whole number of at least `minSeconds`.
 * There is no upper bound: the backend saves a longer timeout as its maximum, so a lowered maximum never blocks a save.
 */
export function isValidExecutionTimeout(seconds: unknown, minSeconds: number): boolean {
    return typeof seconds === 'number' && Number.isInteger(seconds) && seconds >= minSeconds;
}

/** The rule the minimum sets, worded for a message: `at least 5 seconds`. */
export function executionTimeoutMinimumRule(minSeconds: number): string {
    return `at least ${formatDurationInWords(minSeconds)}`;
}

export function executionTimeoutValidator(minSeconds: number): ValidatorFn {
    return ({ value }) => (isValidExecutionTimeout(value, minSeconds) ? null : { executionTimeout: { minSeconds } });
}
