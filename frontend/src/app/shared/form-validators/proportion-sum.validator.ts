import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

// Tolerates float noise such as 0.7 + 0.3, which must count as exactly 1.
const PROPORTION_SUM_TOLERANCE = 1e-9;

/**
 * Group validator: the two proportion fields together must not exceed 1.
 * @returns `{ proportionSum: true }` if they do, otherwise `null`.
 */
export function proportionSumValidator(firstField: string, secondField: string): ValidatorFn {
    return (group: AbstractControl): ValidationErrors | null => {
        const first = Number(group.get(firstField)?.value ?? 0);
        const second = Number(group.get(secondField)?.value ?? 0);
        return first + second > 1 + PROPORTION_SUM_TOLERANCE ? { proportionSum: true } : null;
    };
}
