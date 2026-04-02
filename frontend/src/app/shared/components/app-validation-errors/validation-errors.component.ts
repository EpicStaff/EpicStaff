import { Component, input } from '@angular/core';
import { AbstractControl } from '@angular/forms';

type MinError = { min: number };
type MaxError = { max: number };
type LengthError = { requiredLength: number; actualLength: number };

@Component({
    selector: 'app-validation-errors',
    templateUrl: './validation-errors.component.html',
    styleUrls: ['./validation-errors.component.scss'],
})
export class ValidationErrorsComponent {
    control = input.required<AbstractControl>();

    private messages: Record<string, (error: unknown) => string> = {
        required: () => 'This field is required.',
        min: (error: unknown) => `Min value is ${(error as MinError).min}.`,
        max: (error: unknown) => `Max value is ${(error as MaxError).max}.`,
        minlength: (error: unknown) =>
            `Min length is ${(error as LengthError).requiredLength}. Current length is ${(error as LengthError).actualLength}.`,
        maxlength: (error: unknown) =>
            `Max length is ${(error as LengthError).requiredLength}. Current length is ${(error as LengthError).actualLength}.`,
        pattern: () => `The value does not match the required pattern.`,
        email: () => `Invalid email address.`,
        other: (error: unknown) => String(error),
    };

    get errors(): string[] {
        const errors = this.control()?.errors;
        if (!errors) return [];

        return Object.keys(errors).map((key) => {
            const error = errors![key];
            if (this.messages[key]) {
                return this.messages[key](error);
            }
            return `${key} is invalid.`;
        });
    }
}
