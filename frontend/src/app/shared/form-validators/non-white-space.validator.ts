import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

export function notWhitespaceValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
        const isWhitespace = control.value.length && !control.value.trim().length;
        const isValid = !isWhitespace;
        return isValid ? null : { whitespace: true };
    };
}
