import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

function isEmpty(value: unknown): boolean {
    return value === null || value === undefined || value === '';
}

/**
 * Group validator: the input and output price are set together or both left empty.
 * A price on one side only cannot be used to cost a call, so the API rejects it.
 * @returns `{ pricePair: true }` if exactly one of them is set, otherwise `null`.
 */
export function pricePairValidator(inputPriceField: string, outputPriceField: string): ValidatorFn {
    return (group: AbstractControl): ValidationErrors | null => {
        const isInputEmpty = isEmpty(group.get(inputPriceField)?.value);
        const isOutputEmpty = isEmpty(group.get(outputPriceField)?.value);
        return isInputEmpty === isOutputEmpty ? null : { pricePair: true };
    };
}
