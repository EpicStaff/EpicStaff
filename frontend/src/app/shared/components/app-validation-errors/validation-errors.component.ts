import { Component, input } from '@angular/core';
import { AbstractControl } from '@angular/forms';

@Component({
    selector: 'app-validation-errors',
    templateUrl: './validation-errors.component.html',
    styleUrls: ['./validation-errors.component.scss']
})
export class ValidationErrorsComponent {
    control = input.required<AbstractControl>();

    private messages: Record<string, (error: any) => string> = {
        required: () => 'This field is required.',
        min: (error: any) => `Min value is ${error.min}.`,
        max: (error: any) => `Max value is ${error.max}.`,
        minlength: (error: any) => `Min length is ${error.requiredLength}. Current length is ${error.actualLength}.`,
        maxlength: (error: any) => `Max length is ${error.requiredLength}. Current length is ${error.actualLength}.`,
        pattern: (error: any) => `The value does not match the required pattern.`,
        email: () => `Invalid email address.`,
        other: (error: string) => error,
        // other validators
    };

    get errors(): string[] {
        const errors = this.control()?.errors;
        if (!errors) return [];

        return Object.keys(errors).map(key => {
            const error = errors![key];
            if (this.messages[key]) {
                return this.messages[key](error);
            }
            return `${key} is invalid.`;
        });
    }
}
