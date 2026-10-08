import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

// Mirrors `_validate_new_account_email` in rbac/validation/base.py: same accept/reject result.
const EMAIL_MAX_LENGTH = 254;
const LOCAL_PART_MAX_LENGTH = 64;
const LOCAL_PART_CHARACTERS = /^[A-Za-z0-9._+-]+$/;
const LOCAL_PART_EDGES = /^[A-Za-z0-9](?:.*[A-Za-z0-9])?$/;
const DOMAIN = /^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;

/** New accounts only; login and password reset keep `strictEmailValidator`. */
export function newAccountEmailValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
        const value: unknown = control.value;
        if (typeof value !== 'string' || !value) return null;

        if (/\s/.test(value)) return { emailWhitespace: true };

        const atIndex = value.lastIndexOf('@');
        const localPart = value.slice(0, atIndex);
        const domain = value.slice(atIndex + 1);
        if (atIndex <= 0 || !domain || localPart.split('.').includes('')) return { email: true };
        if (value.length > EMAIL_MAX_LENGTH || localPart.length > LOCAL_PART_MAX_LENGTH) {
            return { emailLength: true };
        }
        if (!LOCAL_PART_CHARACTERS.test(localPart)) return { emailCharacters: true };
        if (!LOCAL_PART_EDGES.test(localPart)) return { emailEdges: true };
        if (!DOMAIN.test(domain)) return { email: true };
        return null;
    };
}
