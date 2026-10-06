import { ValidatorFn, Validators } from '@angular/forms';

/** The server's limit on one secret slot value. */
export const PLUGIN_SECRET_VALUE_MAX_LENGTH = 4096;

/**
 * The server's rules for a slot value that was entered: not only whitespace, at most
 * {@link PLUGIN_SECRET_VALUE_MAX_LENGTH} characters. Add `Validators.required` where a value is mandatory.
 */
export function pluginSecretValueValidators(): ValidatorFn[] {
    return [Validators.pattern(/\S/), Validators.maxLength(PLUGIN_SECRET_VALUE_MAX_LENGTH)];
}
