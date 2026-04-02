import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

export function chunkSizeGreaterThanOverlapValidator(): ValidatorFn {
    return (group: AbstractControl): ValidationErrors | null => {
        const chunkSize = group.get('chunkSize')?.value;
        const overlapSize = group.get('overlapSize')?.value;

        if (chunkSize === null || overlapSize === null) {
            return null;
        }

        return chunkSize <= overlapSize ? { chunkSizeTooSmall: { chunkSize, overlapSize } } : null;
    };
}
