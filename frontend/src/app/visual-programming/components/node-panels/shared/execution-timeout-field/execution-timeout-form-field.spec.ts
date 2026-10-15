import { ExecutionTimeoutLimits } from '../../../../core/models/execution-timeout-limits.model';
import { ExecutionTimeoutFormField, MAX_STORABLE_SECONDS } from './execution-timeout-form-field';

const LIMITS: ExecutionTimeoutLimits = { minSeconds: 5, defaultSeconds: 120, maxSeconds: 3600 };

describe('ExecutionTimeoutFormField', () => {
    it('shows the stored timeout, valid and pristine, and keeps it', () => {
        const field = new ExecutionTimeoutFormField(90, LIMITS);

        expect(field.control.value).toBe(90);
        expect(field.control.valid).toBe(true);
        expect(field.control.dirty).toBe(false);
        expect(field.value).toBe(90);
    });

    it('shows the default for a code without a timeout, and keeps none until edited', () => {
        const field = new ExecutionTimeoutFormField(undefined, LIMITS);

        expect(field.control.value).toBe(LIMITS.defaultSeconds);
        expect(field.value).toBeUndefined();
    });

    it('keeps an edit and marks the control dirty', () => {
        const field = new ExecutionTimeoutFormField(undefined, LIMITS);

        field.edit(300);

        expect(field.control.value).toBe(300);
        expect(field.control.dirty).toBe(true);
        expect(field.value).toBe(300);
    });

    it('keeps an edit that lands on the default, so the code no longer follows the backend default', () => {
        const field = new ExecutionTimeoutFormField(undefined, LIMITS);

        field.edit(LIMITS.defaultSeconds);

        expect(field.value).toBe(LIMITS.defaultSeconds);
    });

    it('reads as edited from within the change the edit reports', () => {
        const field = new ExecutionTimeoutFormField(undefined, LIMITS);
        const seen: (number | undefined)[] = [];
        field.control.valueChanges.subscribe(() => seen.push(field.value));

        field.edit(300);

        expect(seen).toEqual([300]);
    });

    it('caps an edit above the maximum at the maximum', () => {
        const field = new ExecutionTimeoutFormField(90, LIMITS);

        field.edit(LIMITS.maxSeconds! + 1);

        expect(field.control.value).toBe(LIMITS.maxSeconds);
        expect(field.value).toBe(LIMITS.maxSeconds);
    });

    it('caps an edit only at what the backend can store when there is no maximum', () => {
        const field = new ExecutionTimeoutFormField(90, { ...LIMITS, maxSeconds: null });

        field.edit(1_000_000);
        expect(field.value).toBe(1_000_000);

        field.edit(MAX_STORABLE_SECONDS + 1);
        expect(field.value).toBe(MAX_STORABLE_SECONDS);
    });

    it('keeps a stored timeout above the maximum as it is, and valid: the backend saves it as the maximum', () => {
        const field = new ExecutionTimeoutFormField(7200, LIMITS);

        expect(field.control.value).toBe(7200);
        expect(field.control.valid).toBe(true);
        expect(field.value).toBe(7200);
    });

    it('is invalid below the minimum', () => {
        const field = new ExecutionTimeoutFormField(90, LIMITS);

        field.edit(LIMITS.minSeconds - 1);

        expect(field.control.errors).toEqual({ executionTimeout: { minSeconds: LIMITS.minSeconds } });
    });
});
