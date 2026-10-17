import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

export function notWhitespaceValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
        const value: unknown = control.value;
        // Not a string (null before a value is set): nothing to check, `required` reports a missing value.
        if (typeof value !== 'string') return null;
        const isWhitespace = value.length > 0 && value.trim().length === 0;
        return isWhitespace ? { whitespace: true } : null;
    };
}
