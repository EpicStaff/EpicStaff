import { Component, computed, effect, input, output, signal, untracked } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { FormControl, FormRecord } from '@angular/forms';
import { JsonSchema, JsonSchemaProperty, SchemaFieldError } from '@shared/models';
import { deepEqual } from '@shared/utils';
import { switchMap } from 'rxjs';

import { ActivateButtonComponent } from '../activate-button/activate-button.component';
import { SchemaFieldComponent } from './schema-field/schema-field.component';

interface SchemaFormField {
    name: string;
    property: JsonSchemaProperty;
    required: boolean;
    /** The schema gives a default, so the field can go back to it. */
    resettable: boolean;
}

interface SchemaFormGroup {
    /** The schema's raw `x-group`; empty for the fields that name no group. */
    key: string;
    /** Empty for the fields that name no group: they are shown without a heading. */
    label: string;
    fields: SchemaFormField[];
}

/**
 * Edits an object against its JSON Schema: one control per property, picked by `x-widget` and grouped by `x-group`
 * in the order the schema lists them. A property missing from `value` is shown "not set": the form never fills in a
 * default by itself, so what it shows is what `value` holds. Defaults come back only through `resetField`/`resetAll`.
 *
 * `valueChange` emits the whole object on every edit, holding only the schema's properties: one that is "not set"
 * (null, an empty text or list) is left out. Limits are kept by the controls themselves; the server checks the rest,
 * and its errors (`errors`, matched by `<path>.<property>`) are shown under their fields.
 */
@Component({
    selector: 'app-schema-form',
    imports: [ActivateButtonComponent, SchemaFieldComponent],
    templateUrl: './schema-form.component.html',
    styleUrl: './schema-form.component.scss',
})
export class SchemaFormComponent {
    readonly schema = input.required<JsonSchema>();
    readonly value = input<Record<string, unknown>>({});
    /** The server's refusal of the last save; each error names its field by dotted path. */
    readonly errors = input<readonly SchemaFieldError[]>([]);
    /** Where the value sits in the saved object, e.g. `parameters`: `parameters.temperature` is then `temperature`. */
    readonly path = input('');
    /** Display names of a select's options, by property and raw value; an option without one shows its raw value. */
    readonly optionLabels = input<Readonly<Partial<Record<string, Readonly<Record<string, string>>>>>>({});
    /** A text field's placeholder, by property, e.g. a sample value. */
    readonly placeholders = input<Readonly<Partial<Record<string, string>>>>({});
    readonly valueChange = output<Record<string, unknown>>();

    protected readonly groups = computed<SchemaFormGroup[]>(() => groupFields(this.schema()));
    protected readonly form = computed(() => {
        const form = new FormRecord<FormControl<unknown>>({});
        for (const name of Object.keys(this.schema().properties)) form.addControl(name, new FormControl<unknown>(null));
        return form;
    });
    /** The server's reason per property; several reasons for one property are joined. */
    protected readonly fieldErrors = computed<Readonly<Record<string, string>>>(() => {
        const prefix = this.path() ? `${this.path()}.` : '';
        const messages: Record<string, string> = {};
        for (const error of this.errors()) {
            if (!error.field.startsWith(prefix)) continue;
            const name = error.field.slice(prefix.length);
            messages[name] = messages[name] ? `${messages[name]} ${error.reason}` : error.reason;
        }
        return messages;
    });
    /** What the controls hold now, as `valueChange` emits it. */
    private readonly current = signal<Record<string, unknown>>({});

    constructor() {
        effect(() => {
            const form = this.form();
            const properties = this.schema().properties;
            const value = this.value();
            untracked(() => {
                const target = shownValues(properties, value);
                // An echo of what the form just emitted is not written back: that would reformat a JSON field being typed.
                if (!deepEqual(controlValues(form, properties), target)) {
                    // Each control tells its own field (a secret picker lists its current value); the form stays silent.
                    for (const [name, control] of Object.entries(form.controls)) {
                        control.setValue(target[name], { onlySelf: true });
                    }
                    form.updateValueAndValidity({ emitEvent: false });
                }
                this.current.set(collect(form, properties));
            });
        });
        toObservable(this.form)
            .pipe(
                switchMap((form) => form.valueChanges),
                takeUntilDestroyed()
            )
            .subscribe(() => {
                const value = collect(this.form(), this.schema().properties);
                this.current.set(value);
                this.valueChange.emit(value);
            });
    }

    /** Puts one property back to its default. */
    resetField(name: string): void {
        this.form().controls[name]?.setValue(this.schema().properties[name]?.default ?? null);
    }

    /** Puts every property back to its default. */
    resetAll(): void {
        const defaults: Record<string, unknown> = {};
        for (const [name, property] of Object.entries(this.schema().properties))
            defaults[name] = property.default ?? null;
        this.form().setValue(defaults);
    }

    protected control(name: string): FormControl<unknown> {
        return this.form().controls[name];
    }

    protected isDefault(field: SchemaFormField): boolean {
        return deepEqual(this.current()[field.name] ?? null, field.property.default ?? null);
    }

    protected fieldId(name: string): string {
        return `schema-field-${this.path() || 'value'}-${name}`;
    }
}

function groupFields(schema: JsonSchema): SchemaFormGroup[] {
    const required = new Set(schema.required ?? []);
    const groups = new Map<string, SchemaFormGroup>();
    for (const [name, property] of Object.entries(schema.properties)) {
        const key = property['x-group'] ?? '';
        let group = groups.get(key);
        if (!group) {
            group = { key, label: key.charAt(0).toUpperCase() + key.slice(1), fields: [] };
            groups.set(key, group);
        }
        group.fields.push({ name, property, required: required.has(name), resettable: 'default' in property });
    }
    return [...groups.values()];
}

/** Each control's value: the given one, else "not set". */
function shownValues(properties: Record<string, JsonSchemaProperty>, value: Record<string, unknown>) {
    const values: Record<string, unknown> = {};
    for (const name of Object.keys(properties)) values[name] = value[name] ?? null;
    return values;
}

/** What each control holds, a JSON field's text parsed once it parses. */
function controlValues(
    form: FormRecord<FormControl<unknown>>,
    properties: Record<string, JsonSchemaProperty>
): Record<string, unknown> {
    const values: Record<string, unknown> = {};
    for (const [name, control] of Object.entries(form.controls)) {
        const value = control.value ?? null;
        values[name] = properties[name]?.['x-widget'] === 'json' ? parseJsonText(value) : value;
    }
    return values;
}

function collect(
    form: FormRecord<FormControl<unknown>>,
    properties: Record<string, JsonSchemaProperty>
): Record<string, unknown> {
    const value: Record<string, unknown> = {};
    for (const [name, fieldValue] of Object.entries(controlValues(form, properties))) {
        if (fieldValue === null || fieldValue === '' || (Array.isArray(fieldValue) && fieldValue.length === 0))
            continue;
        value[name] = fieldValue;
    }
    return value;
}

/** The JSON editor hands over the text being typed: sent parsed once it parses, as typed until then. */
function parseJsonText(value: unknown): unknown {
    if (typeof value !== 'string') return value;
    try {
        return JSON.parse(value) as unknown;
    } catch {
        return value;
    }
}
