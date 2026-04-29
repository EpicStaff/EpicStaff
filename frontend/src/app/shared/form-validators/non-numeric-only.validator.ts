import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

export function notNumericOnlyValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
        const value: string = control.value;
        if (!value) return null;
        return /^\d+$/.test(value) ? { numericOnly: true } : null;
    };
}
