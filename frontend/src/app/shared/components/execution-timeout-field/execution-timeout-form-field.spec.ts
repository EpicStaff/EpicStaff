import { TEST_EXECUTION_TIMEOUT_LIMITS } from '../../services/execution-timeout-limits/execution-timeout-limits.testing';
import { ExecutionTimeoutFormField, MAX_STORABLE_SECONDS } from './execution-timeout-form-field';

describe('ExecutionTimeoutFormField', () => {
    it('shows the stored timeout, valid and pristine, and keeps it', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);

        expect(field.control.value).toBe(90);
        expect(field.control.valid).toBe(true);
        expect(field.control.dirty).toBe(false);
        expect(field.value).toBe(90);
    });

    it('shows the default for a code without a timeout, and keeps none until edited', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);

        expect(field.control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.defaultSeconds);
        expect(field.value).toBeUndefined();
    });

    it('keeps an edit and marks the control dirty', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);

        field.edit(300);

        expect(field.control.value).toBe(300);
        expect(field.control.dirty).toBe(true);
        expect(field.value).toBe(300);
    });

    it('keeps an edit that lands on the default, so the code no longer follows the backend default', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);

        field.edit(TEST_EXECUTION_TIMEOUT_LIMITS.defaultSeconds);

        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.defaultSeconds);
    });

    it('reads as edited from within the change the edit reports', () => {
        const field = new ExecutionTimeoutFormField(undefined, TEST_EXECUTION_TIMEOUT_LIMITS);
        const seen: (number | undefined)[] = [];
        field.control.valueChanges.subscribe(() => seen.push(field.value));

        field.edit(300);

        expect(seen).toEqual([300]);
    });

    it('caps an edit above the maximum at the maximum', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);

        field.edit(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds! + 1);

        expect(field.control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
    });

    it('caps an edit only at what the backend can store when there is no maximum', () => {
        const field = new ExecutionTimeoutFormField(90, { ...TEST_EXECUTION_TIMEOUT_LIMITS, maxSeconds: null });

        field.edit(1_000_000);
        expect(field.value).toBe(1_000_000);

        field.edit(MAX_STORABLE_SECONDS + 1);
        expect(field.value).toBe(MAX_STORABLE_SECONDS);
    });

    it('keeps a stored timeout above the maximum as it is, and valid: the backend saves it as the maximum', () => {
        const field = new ExecutionTimeoutFormField(7200, TEST_EXECUTION_TIMEOUT_LIMITS);

        expect(field.control.value).toBe(7200);
        expect(field.control.valid).toBe(true);
        expect(field.value).toBe(7200);
    });

    it('steps the timeout up and down, marking the control dirty', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);

        field.step(30);
        expect(field.control.value).toBe(120);
        expect(field.control.dirty).toBe(true);
        expect(field.value).toBe(120);

        field.step(-30);
        expect(field.value).toBe(90);
    });

    it('steps no lower than the minimum, nor higher than the maximum', () => {
        const field = new ExecutionTimeoutFormField(20, TEST_EXECUTION_TIMEOUT_LIMITS);

        field.step(-30);
        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds);

        field.edit(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds! - 10);
        field.step(30);
        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
    });

    it('steps a stored timeout above the maximum into the limits', () => {
        const field = new ExecutionTimeoutFormField(7200, TEST_EXECUTION_TIMEOUT_LIMITS);

        field.step(-30);

        expect(field.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds);
    });

    it('steps a stored timeout below the minimum up from where it is', () => {
        const field = new ExecutionTimeoutFormField(2, TEST_EXECUTION_TIMEOUT_LIMITS);

        field.step(30);

        expect(field.value).toBe(32);
        expect(field.control.valid).toBe(true);
    });

    it('steps up to what the backend can store when there is no maximum', () => {
        const field = new ExecutionTimeoutFormField(MAX_STORABLE_SECONDS - 10, {
            ...TEST_EXECUTION_TIMEOUT_LIMITS,
            maxSeconds: null,
        });

        expect(field.upperBound).toBe(MAX_STORABLE_SECONDS);
        field.step(30);
        expect(field.value).toBe(MAX_STORABLE_SECONDS);
    });

    it('is invalid below the minimum', () => {
        const field = new ExecutionTimeoutFormField(90, TEST_EXECUTION_TIMEOUT_LIMITS);

        field.edit(TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds - 1);

        expect(field.control.errors).toEqual({
            executionTimeout: { minSeconds: TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds },
        });
    });
});
