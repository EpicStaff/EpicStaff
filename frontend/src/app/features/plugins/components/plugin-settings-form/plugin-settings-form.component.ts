import { DatePipe } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { FormControl, FormRecord, ReactiveFormsModule } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
    SelectComponent,
    SelectItem,
    TextareaComponent,
    ToggleSwitchComponent,
} from '@shared/components';
import { catchError, finalize, merge, of, switchMap, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginSettingScalar, PluginSettingsResponse, PluginSettingState } from '../../models/plugin-backend.model';
import { PluginErrorItem, PluginErrorView } from '../../models/plugin-error.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

/** What happens to a stored secret on save: nothing, a new value, or removal. */
type SecretEdit = 'keep' | 'replace' | 'clear';

/** A setting control's value: `boolean` for a toggle, `null` for an enum left unset, else text (integers too, so a
 *  negative number can be typed). */
type SettingControlValue = string | boolean | null;

/** Shown in front of a stored secret's last characters. */
export const SECRET_MASK = '••••';

/** `values.<key>` in an `errors[]` item's `loc`. */
const SETTING_LOC_PREFIX = 'values.';

/** A whole number, optionally negative. */
const INTEGER_PATTERN = /^-?\d+$/;

/**
 * A backend plugin's settings, one control per type: enum → select, boolean → toggle, text → textarea, the rest a text
 * input. A secret is write-only: never shown or prefilled, only its last characters; it can be set, replaced or
 * cleared. Any other stored setting can go back to its default ("Use default"). A save sends only the changed keys,
 * and restarts the plugin.
 *
 * A setting that is not stored counts as changed once its control is touched, whatever it then holds (a toggle left
 * Off is a choice too); a required one the plugin waits for counts as changed from the start, so it can be saved as it
 * is shown.
 */
@Component({
    selector: 'app-plugin-settings-form',
    imports: [
        ButtonComponent,
        CustomInputComponent,
        DatePipe,
        FetchErrorStateComponent,
        LoadingSpinnerComponent,
        ReactiveFormsModule,
        SelectComponent,
        TextareaComponent,
        ToggleSwitchComponent,
    ],
    templateUrl: './plugin-settings-form.component.html',
    styleUrl: './plugin-settings-form.component.scss',
})
export class PluginSettingsFormComponent {
    readonly identifier = input.required<string>();
    /** After a save; the plugin restarts with the new values. */
    readonly saved = output<PluginSettingsResponse>();

    protected readonly response = signal<PluginSettingsResponse | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<PluginErrorView | null>(null);
    protected readonly isSaving = signal(false);
    protected readonly saveError = signal<PluginErrorView | null>(null);
    /** The server's message per setting key, from the last refused save. */
    protected readonly fieldErrors = signal<Readonly<Record<string, string>>>({});
    protected readonly secretEdits = signal<Readonly<Record<string, SecretEdit>>>({});
    /** Stored settings to put back to their default on save. */
    protected readonly resets = signal<ReadonlySet<string>>(new Set());
    /** Bumped on every control change, so the computed state below follows the form. */
    private readonly formRevision = signal(0);
    /** Integer settings whose text is not a whole number EpicStaff can store. */
    protected readonly invalidIntegers = computed<ReadonlySet<string>>(() => {
        this.formRevision();
        const invalid = new Set<string>();
        for (const setting of this.response()?.settings ?? []) {
            if (setting.type !== 'integer') continue;
            const text = this.controlValue(setting.key);
            if (typeof text === 'string' && text.trim() !== '' && parseInteger(text) === null) invalid.add(setting.key);
        }
        return invalid;
    });
    /** What a save would send: the changed keys only. */
    protected readonly changes = computed<Record<string, PluginSettingScalar | null>>(() => {
        this.formRevision();
        return this.collectChanges(this.response(), this.secretEdits(), this.resets());
    });
    protected readonly canSave = computed(
        () => !this.isSaving() && Object.keys(this.changes()).length > 0 && this.invalidIntegers().size === 0
    );
    protected readonly missingRequiredLabels = computed<string[]>(() => {
        const response = this.response();
        if (!response) return [];
        const labels = new Map(response.settings.map((setting) => [setting.key, setting.label]));
        return response.missing_required.map((key) => labels.get(key) ?? key);
    });
    /** Problems of a refused save that belong to no field. */
    protected readonly otherErrorItems = computed<PluginErrorItem[]>(
        () => this.saveError()?.items.filter((item) => !item.loc.startsWith(SETTING_LOC_PREFIX)) ?? []
    );
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({ identifier: this.identifier(), reload: this.reloads() }));

    protected readonly form = new FormRecord<FormControl<SettingControlValue>>({});
    protected readonly secretValues = new FormRecord<FormControl<string>>({});
    protected readonly secretMask = SECRET_MASK;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        merge(this.form.valueChanges, this.secretValues.valueChanges)
            .pipe(takeUntilDestroyed())
            .subscribe(() => this.formRevision.update((revision) => revision + 1));
        toObservable(this.request)
            .pipe(
                tap(() => {
                    this.isLoading.set(true);
                    this.loadError.set(null);
                }),
                switchMap(({ identifier }) =>
                    this.storage.getSettings(identifier).pipe(
                        catchError((error: unknown) => {
                            this.loadError.set(toPluginErrorView(error, "Couldn't load the settings."));
                            return of(null);
                        }),
                        finalize(() => this.isLoading.set(false))
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((response) => {
                if (response) this.show(response);
            });
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    protected control(key: string): FormControl<SettingControlValue> {
        return this.form.controls[key];
    }

    protected secretControl(key: string): FormControl<string> {
        return this.secretValues.controls[key];
    }

    protected secretEdit(key: string): SecretEdit {
        return this.secretEdits()[key] ?? 'keep';
    }

    protected enumItems(setting: PluginSettingState): SelectItem<string>[] {
        return (setting.values ?? []).map((value) => ({ name: value, value }));
    }

    protected fieldId(setting: PluginSettingState): string {
        return `plugin-setting-${setting.key}`;
    }

    /** The message under a field: the server's for it, else why its text cannot be saved, else empty. */
    protected fieldError(setting: PluginSettingState): string {
        const serverMessage = this.fieldErrors()[setting.key];
        if (serverMessage) return serverMessage;
        return this.invalidIntegers().has(setting.key) ? 'Enter a whole number.' : '';
    }

    /** A stored setting that is not secret can go back to its default, unless it is required and has none. */
    protected canReset(setting: PluginSettingState): boolean {
        return setting.is_set && setting.type !== 'secret' && (!setting.required || setting.default !== null);
    }

    protected isReset(key: string): boolean {
        return this.resets().has(key);
    }

    /** Shows the default in the control, which stays locked until Undo; the save sends `null`. */
    protected resetToDefault(setting: PluginSettingState): void {
        const control = this.control(setting.key);
        control.setValue(initialValue({ ...setting, is_set: false, value: null }));
        control.disable();
        this.resets.update((keys) => new Set([...keys, setting.key]));
    }

    protected undoReset(setting: PluginSettingState): void {
        const control = this.control(setting.key);
        control.enable();
        control.setValue(initialValue(setting));
        control.markAsPristine();
        this.resets.update((keys) => new Set([...keys].filter((key) => key !== setting.key)));
    }

    protected defaultLabel(setting: PluginSettingState): string | null {
        if (setting.default === null) return null;
        if (typeof setting.default === 'boolean') return setting.default ? 'On' : 'Off';
        return String(setting.default);
    }

    protected replaceSecret(key: string): void {
        this.secretControl(key).setValue('');
        this.setSecretEdit(key, 'replace');
    }

    protected clearSecret(key: string): void {
        this.secretControl(key).setValue('');
        this.setSecretEdit(key, 'clear');
    }

    protected keepSecret(key: string): void {
        this.secretControl(key).setValue('');
        this.setSecretEdit(key, 'keep');
    }

    protected save(): void {
        if (!this.canSave()) return;
        this.isSaving.set(true);
        this.saveError.set(null);
        this.fieldErrors.set({});
        this.storage
            .updateSettings(this.identifier(), { values: this.changes() })
            .pipe(
                finalize(() => this.isSaving.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (response) => {
                    this.show(response);
                    this.toast.success('Settings saved. The plugin restarts to use them.');
                    this.saved.emit(response);
                },
                error: (error: unknown) => {
                    const view = toPluginErrorView(error, "Couldn't save the settings.");
                    this.fieldErrors.set(fieldErrorsOf(view.items));
                    this.saveError.set(view);
                },
            });
    }

    /** Rebuilds the controls from the server's state: every edit is dropped, secrets start empty. */
    private show(response: PluginSettingsResponse): void {
        for (const key of Object.keys(this.form.controls)) this.form.removeControl(key, { emitEvent: false });
        for (const key of Object.keys(this.secretValues.controls)) {
            this.secretValues.removeControl(key, { emitEvent: false });
        }
        for (const setting of response.settings) {
            if (setting.type === 'secret') {
                this.secretValues.addControl(setting.key, new FormControl('', { nonNullable: true }), {
                    emitEvent: false,
                });
            } else {
                this.form.addControl(setting.key, new FormControl<SettingControlValue>(initialValue(setting)), {
                    emitEvent: false,
                });
            }
        }
        this.response.set(response);
        this.secretEdits.set({});
        this.resets.set(new Set());
        this.fieldErrors.set({});
        this.formRevision.update((revision) => revision + 1);
    }

    private setSecretEdit(key: string, edit: SecretEdit): void {
        this.secretEdits.update((edits) => ({ ...edits, [key]: edit }));
    }

    private controlValue(key: string): SettingControlValue | undefined {
        return this.form.controls[key]?.value;
    }

    private collectChanges(
        response: PluginSettingsResponse | null,
        secretEdits: Readonly<Record<string, SecretEdit>>,
        resets: ReadonlySet<string>
    ): Record<string, PluginSettingScalar | null> {
        const values: Record<string, PluginSettingScalar | null> = {};
        const awaited = new Set(response?.missing_required ?? []);
        for (const setting of response?.settings ?? []) {
            if (setting.type === 'secret') {
                const edit = secretEdits[setting.key] ?? 'keep';
                const replacement = this.secretValues.controls[setting.key]?.value ?? '';
                if (edit === 'clear' && setting.is_set) values[setting.key] = null;
                if (edit === 'replace' && replacement !== '') values[setting.key] = replacement;
                continue;
            }
            if (resets.has(setting.key)) {
                values[setting.key] = null;
                continue;
            }
            const control = this.form.controls[setting.key];
            if (!control) continue;
            if (setting.is_set) {
                if (control.value !== initialValue(setting))
                    values[setting.key] = toStoredValue(setting, control.value);
                continue;
            }
            // Not stored: what the admin picked, once they touched it (or at once for a required one the plugin
            // waits for); an empty field stays unset.
            if (!control.dirty && !awaited.has(setting.key)) continue;
            const picked = toStoredValue(setting, control.value);
            if (picked !== null) values[setting.key] = picked;
        }
        return values;
    }
}

/** What a control starts with: the stored value, else the default, else empty. */
function initialValue(setting: PluginSettingState): SettingControlValue {
    const value = setting.is_set ? setting.value : setting.default;
    switch (setting.type) {
        case 'boolean':
            return value === true;
        case 'enum':
            return typeof value === 'string' ? value : null;
        default:
            return value === null ? '' : String(value);
    }
}

/** The value to send for a changed control; an emptied field clears the stored value. */
function toStoredValue(setting: PluginSettingState, current: SettingControlValue): PluginSettingScalar | null {
    if (typeof current === 'boolean') return current;
    if (current === null || current === '') return null;
    if (setting.type === 'integer') return parseInteger(current);
    return current;
}

function parseInteger(text: string): number | null {
    const trimmed = text.trim();
    if (!INTEGER_PATTERN.test(trimmed)) return null;
    const value = Number(trimmed);
    return Number.isSafeInteger(value) ? value : null;
}

function fieldErrorsOf(items: PluginErrorItem[]): Record<string, string> {
    const errors: Record<string, string> = {};
    for (const item of items) {
        if (!item.loc.startsWith(SETTING_LOC_PREFIX)) continue;
        const key = item.loc.slice(SETTING_LOC_PREFIX.length);
        errors[key] = errors[key] ? `${errors[key]} ${item.message}` : item.message;
    }
    return errors;
}
