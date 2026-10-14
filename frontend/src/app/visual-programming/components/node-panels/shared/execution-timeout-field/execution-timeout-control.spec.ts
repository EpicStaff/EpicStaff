import { createExecutionTimeoutField } from './execution-timeout-control';

describe('createExecutionTimeoutField', () => {
    it('starts at the stored timeout, valid and untouched', () => {
        const field = createExecutionTimeoutField(5, 60);

        expect(field.control.value).toBe(5);
        expect(field.control.valid).toBe(true);
        expect(field.control.touched).toBe(false);
        expect(field.maxMinutes).toBe(60);
    });

    it('starts a node saved before nodes had a timeout at the ceiling, which the backend applies to it', () => {
        expect(createExecutionTimeoutField(null, 60).control.value).toBe(60);
    });

    it('requires a value', () => {
        const { control } = createExecutionTimeoutField(5, 60);

        control.setValue(null);

        expect(control.errors).toEqual({ required: true });
    });

    it('requires at least 1 minute', () => {
        const { control } = createExecutionTimeoutField(5, 60);

        control.setValue(0);
        expect(control.errors).toEqual({ min: { min: 1, actual: 0 } });

        control.setValue(0.5);
        expect(control.errors).toEqual({ min: { min: 1, actual: 0.5 } });

        control.setValue(1);
        expect(control.valid).toBe(true);
    });

    it('caps an edit above the ceiling at the ceiling', () => {
        const { control } = createExecutionTimeoutField(5, 60);

        control.setValue(60);
        expect(control.value).toBe(60);

        control.setValue(61);
        expect(control.value).toBe(60);
        expect(control.valid).toBe(true);
    });

    it('requires whole minutes', () => {
        const { control } = createExecutionTimeoutField(5, 60);

        control.setValue(2.5);

        expect(control.errors).toEqual({ wholeNumber: true });
    });

    it('keeps a timeout saved under a higher ceiling as it is, and valid: the backend saves it as the ceiling', () => {
        const { control } = createExecutionTimeoutField(90, 60);

        expect(control.value).toBe(90);
        expect(control.valid).toBe(true);
    });

    it('caps an edit of a timeout saved under a higher ceiling at the ceiling', () => {
        const { control } = createExecutionTimeoutField(90, 60);

        control.setValue(89);

        expect(control.value).toBe(60);
    });
});
