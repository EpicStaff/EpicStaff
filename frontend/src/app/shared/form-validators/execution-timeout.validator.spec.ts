import { FormControl } from '@angular/forms';

import {
    executionTimeoutMinimumRule,
    executionTimeoutValidator,
    isValidExecutionTimeout,
} from './execution-timeout.validator';

const MIN_SECONDS = 5;

describe('isValidExecutionTimeout', () => {
    it('accepts a whole number of seconds from the minimum up, with no upper bound', () => {
        expect(isValidExecutionTimeout(MIN_SECONDS, MIN_SECONDS)).toBe(true);
        expect(isValidExecutionTimeout(1_000_000, MIN_SECONDS)).toBe(true);
    });

    it.each([MIN_SECONDS - 1, 0, -10, 7.5, Number.NaN, null, undefined, '30'])('refuses %s', (value) => {
        expect(isValidExecutionTimeout(value, MIN_SECONDS)).toBe(false);
    });
});

describe('executionTimeoutMinimumRule', () => {
    it('words the minimum as a duration', () => {
        expect(executionTimeoutMinimumRule(5)).toBe('at least 5 seconds');
        expect(executionTimeoutMinimumRule(90)).toBe('at least 1 minute 30 seconds');
    });
});

describe('executionTimeoutValidator', () => {
    it('reports the minimum for an invalid value and nothing for a valid one', () => {
        const control = new FormControl<number>(MIN_SECONDS, {
            nonNullable: true,
            validators: executionTimeoutValidator(MIN_SECONDS),
        });
        expect(control.errors).toBeNull();

        control.setValue(MIN_SECONDS - 1);

        expect(control.errors).toEqual({ executionTimeout: { minSeconds: MIN_SECONDS } });
    });
});
