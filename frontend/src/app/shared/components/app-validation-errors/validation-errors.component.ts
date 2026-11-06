import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl } from '@angular/forms';
import { generateUuid } from '@shared/utils';

@Component({
    selector: 'app-validation-errors',
    templateUrl: './validation-errors.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./validation-errors.component.scss'],
    host: { '[attr.id]': 'id()' },
})
export class ValidationErrorsComponent {
    control = input.required<AbstractControl>();
    /** The host's id, for the field to point its `aria-describedby` at, so the reason is read with the field. */
    readonly id = input<string>(`validation-errors-${generateUuid()}`);

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
        venvName: () => 'Use only letters, digits, spaces, - and _.',
        customLibraryName: () => 'Use only letters, digits, - . _, starting and ending with a letter or digit.',
        email: () => 'Invalid email address.',
        emailWhitespace: () => 'Email must not contain whitespace.',
        emailLength: () => 'Must be at most 254 characters, with at most 64 before the @.',
        emailCharacters: () => 'Use only letters, digits and . _ - + before the @.',
        emailEdges: () => 'The part before @ must start and end with a letter or digit.',
        httpUrl: () => 'Must be an http:// or https:// URL.',
        numericOnly: () => 'Password cannot be entirely numeric.',
        whitespace: () => 'Value cannot be blank string.',
        uniqueName: () => 'A tool with this name already exists.',
        tasksRequired: () => 'Add at least one task.',
        taskNameRequired: () => 'Every task needs a name.',
        taskNameDuplicate: () => 'Task names must be unique.',
        taskInstructionsRequired: () => 'Every task needs instructions.',
        invalidNumber: () => 'Enter a valid number. Use a dot as the decimal separator.',
        pricePair: () => "Set both the input and output price, or leave both empty to use the provider's pricing.",
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
            out.push(this.messageFor(key, errs[key]));
        }

        return out;
    });

    // A validator that words its own error carries the message as the error's value.
    private messageFor(key: string, error: unknown): string {
        const formatter = this.messages[key];
        if (formatter) return formatter(error);
        if (typeof error === 'string' && error.trim()) return error;
        return `${key} is invalid.`;
    }
}
