import { Component, computed, effect, inject, input, untracked } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { JsonSchemaProperty, JsonSchemaType, SchemaWidget } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { startWith, switchMap } from 'rxjs';

import { ChipsInputComponent } from '../../chips-input/chips-input.component';
import { ToggleSwitchComponent } from '../../form-controls/toggle-switch/toggle-switch.component';
import { CustomInputComponent } from '../../form-input/form-input.component';
import { JsonEditorFormFieldComponent } from '../../json-editor/json-editor-form-field.component';
import { NumberStepperComponent } from '../../number-stepper/number-stepper.component';
import { SelectComponent, SelectItem } from '../../select/select.component';
import { SliderWithStepperComponent } from '../../slider-with-stepper/slider-with-stepper.component';
import { StringListComponent } from '../../string-list/string-list.component';
import { TextareaComponent } from '../../textarea/textarea.component';

/** What a secret field stores: a reference to an organization secret by name, never its value. */
function secretMarker(name: string): string {
    return `epicstaff_secret(${name})`;
}

/** The secret a marker names; a value that is no marker stands for itself. */
function markedSecretName(marker: string): string {
    return /^epicstaff_secret\(\s*(.+?)\s*\)$/.exec(marker)?.[1] ?? marker;
}

function hasType(property: JsonSchemaProperty, type: JsonSchemaType): boolean {
    return Array.isArray(property.type) ? property.type.includes(type) : property.type === type;
}

/**
 * One value edited with the control its schema names in `x-widget` (a plain text input when it names none). Labels,
 * help text, limits and options come from the schema; an empty `error` shows nothing.
 */
@Component({
    selector: 'app-schema-field',
    imports: [
        ChipsInputComponent,
        CustomInputComponent,
        JsonEditorFormFieldComponent,
        NumberStepperComponent,
        ReactiveFormsModule,
        SelectComponent,
        SliderWithStepperComponent,
        StringListComponent,
        TextareaComponent,
        ToggleSwitchComponent,
    ],
    templateUrl: './schema-field.component.html',
    styleUrl: './schema-field.component.scss',
})
export class SchemaFieldComponent {
    readonly property = input.required<JsonSchemaProperty>();
    readonly control = input.required<FormControl<unknown>>();
    readonly required = input(false);
    /** The message under the field, e.g. the server's reason for refusing it. */
    readonly error = input('');
    /** The text input's id. */
    readonly fieldId = input('');
    readonly placeholder = input('');
    /** A select option's display name by its raw value; an option without one shows the raw value. */
    readonly optionLabels = input<Readonly<Partial<Record<string, string>>>>({});

    protected readonly widget = computed<SchemaWidget>(() => this.property()['x-widget'] ?? 'text');
    protected readonly label = computed(() => this.property().title ?? '');
    protected readonly helpText = computed(() => this.property().description ?? '');
    /** The value may be left "not set". */
    protected readonly nullable = computed(
        () => hasType(this.property(), 'null') || (this.property().enum?.includes(null) ?? false)
    );
    protected readonly integer = computed(() => hasType(this.property(), 'integer'));
    protected readonly step = computed(() => this.property()['x-step'] ?? 1);
    protected readonly selectItems = computed<SelectItem[]>(() => {
        const options: SelectItem[] = (this.property().enum ?? [])
            .filter((option): option is string => option !== null)
            .map((option) => ({ name: this.optionLabels()[option] ?? option, value: option }));
        return this.nullable() ? [{ name: 'Not set', value: null }, ...options] : options;
    });
    /**
     * The organization secrets, plus the stored marker when its secret is not among them (binned, deleted or not
     * visible to this user), so the picker shows what is still sent; an optional field can go back to "Not set".
     */
    protected readonly secretItems = computed<SelectItem[]>(() => {
        const items: SelectItem[] = this.secretsStorage.secrets().map((secret) => ({
            name: secret.name,
            value: secretMarker(secret.name),
            tip: this.secretsStorage.maskTail(secret.tail),
        }));
        const current = this.value();
        if (typeof current === 'string' && current && !items.some((item) => item.value === current)) {
            const name = markedSecretName(current);
            // Until the secrets are loaded nothing is known to be missing.
            items.push({ name: this.secretsStorage.secretsLoaded() ? `${name} (missing)` : name, value: current });
        }
        return this.required() ? items : [{ name: 'Not set', value: null }, ...items];
    });

    private readonly value = toSignal(
        toObservable(this.control).pipe(
            switchMap((control) => control.valueChanges.pipe(startWith<unknown>(control.value)))
        )
    );

    private readonly secretsStorage = inject(SecretsStorageService);

    constructor() {
        effect(() => {
            if (this.widget() !== 'secret') return;
            // Shared and cached by the storage; a failed load leaves the picker empty.
            untracked(() => this.secretsStorage.getSecrets().subscribe({ error: () => undefined }));
        });
    }
}
