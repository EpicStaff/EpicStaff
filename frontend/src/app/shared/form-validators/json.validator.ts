import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

/**
 * JSON Validator
 * Checks whether the control's value is a valid JSON string.
 * @returns `{ jsonInvalid: true }` if invalid, otherwise `null`.
 * Empty strings or null are considered valid.
 */
export function jsonValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
        const value = control.value;

        if (value === null || value === '') {
            return null; // empty value is not considered invalid JSON
        }

        try {
            JSON.parse(value);
            return null; // valid JSON
        } catch {
            return { jsonInvalid: true }; // invalid JSON
        }
    };
}
