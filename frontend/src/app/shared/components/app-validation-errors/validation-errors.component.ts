import { Component, computed, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl } from '@angular/forms';

@Component({
    selector: 'app-validation-errors',
    templateUrl: './validation-errors.component.html',
    styleUrls: ['./validation-errors.component.scss'],
})
export class ValidationErrorsComponent {
    control = input.required<AbstractControl>();

    private destroyRef = inject(DestroyRef);
    private statusTick = signal(0);

    constructor() {
        // Re-subscribe whenever the `control` input changes; tick on each status emission.
        effect((onCleanup) => {
            const c = this.control();
            const sub = c.statusChanges
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(() => this.statusTick.update((n) => n + 1));
            onCleanup(() => sub.unsubscribe());
        });
    }

    private messages: Record<string, (error: unknown) => string> = {
        required: () => 'This field is required.',
        min: (e) => `Min value is ${(e as { min: number }).min}.`,
        max: (e) => `Max value is ${(e as { max: number }).max}.`,
        minlength: (e) => {
            const x = e as { requiredLength: number; actualLength: number };
            return `Min length is ${x.requiredLength}. Current length is ${x.actualLength}.`;
        },
        maxlength: (e) => {
            const x = e as { requiredLength: number; actualLength: number };
            return `Max length is ${x.requiredLength}. Current length is ${x.actualLength}.`;
        },
        pattern: () => 'The value does not match the required pattern.',
        email: () => 'Invalid email address.',
        numericOnly: () => 'Password cannot be entirely numeric.',
        whitespace: () => 'Value cannot be blank string.',
    };

    messagesList = computed<string[]>(() => {
        this.statusTick(); // tick subscription drives recomputation

        const errs = this.control()?.errors;
        if (!errs) return [];

        const out: string[] = [];

        const server = errs['server'];
        if (Array.isArray(server)) out.push(...(server as string[]));

        for (const key of Object.keys(errs)) {
            if (key === 'server') continue;
            const formatter = this.messages[key];
            out.push(formatter ? formatter(errs[key]) : `${key} is invalid.`);
        }

        return out;
    });
}
