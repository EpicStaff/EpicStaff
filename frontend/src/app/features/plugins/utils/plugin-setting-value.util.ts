import { FormControl, FormRecord } from '@angular/forms';

import { PluginSettingNeeded } from '../models/plugin-admin.model';
import { PluginSettingScalar } from '../models/plugin-backend.model';

/** A whole number, optionally negative. */
const INTEGER_PATTERN = /^-?\d+$/;

/** A setting control's value: `boolean` for a toggle, `null` for an enum left unset, else text (integers too). */
export type PluginSettingControlValue = string | boolean | null;

export type PluginNeededSettingsForm = FormRecord<FormControl<PluginSettingControlValue>>;

/** `text` as an integer setting's value; `null` when it is not a whole number EpicStaff can store. */
export function parsePluginInteger(text: string): number | null {
    const trimmed = text.trim();
    if (!INTEGER_PATTERN.test(trimmed)) return null;
    const value = Number(trimmed);
    return Number.isSafeInteger(value) ? value : null;
}

/** One empty control per setting a new version needs: a toggle starts Off, the others empty. */
export function createNeededSettingsForm(settings: readonly PluginSettingNeeded[]): PluginNeededSettingsForm {
    const form: PluginNeededSettingsForm = new FormRecord<FormControl<PluginSettingControlValue>>({});
    for (const setting of settings) {
        const initial: PluginSettingControlValue =
            setting.type === 'boolean' ? false : setting.type === 'enum' ? null : '';
        form.addControl(setting.key, new FormControl<PluginSettingControlValue>(initial));
    }
    return form;
}

/**
 * The values to send for the settings a new version needs, once every one of them has a value its type accepts;
 * `null` while one is missing or not valid. A secret is sent exactly as typed.
 */
export function neededSettingValues(
    settings: readonly PluginSettingNeeded[],
    form: PluginNeededSettingsForm
): Record<string, PluginSettingScalar> | null {
    const values: Record<string, PluginSettingScalar> = {};
    for (const setting of settings) {
        const value = neededSettingValue(setting, form.controls[setting.key]?.value ?? null);
        if (value === null) return null;
        values[setting.key] = value;
    }
    return values;
}

/** Why a needed setting's current text cannot be sent, for the message under it; `null` when it can, or is empty. */
export function neededSettingProblem(setting: PluginSettingNeeded, value: PluginSettingControlValue): string | null {
    if (setting.type !== 'integer' || typeof value !== 'string' || value.trim() === '') return null;
    return parsePluginInteger(value) === null ? 'Enter a whole number.' : null;
}

function neededSettingValue(
    setting: PluginSettingNeeded,
    value: PluginSettingControlValue
): PluginSettingScalar | null {
    if (typeof value === 'boolean') return value;
    if (value === null) return null;
    switch (setting.type) {
        case 'enum':
            return (setting.values ?? []).includes(value) ? value : null;
        case 'integer':
            return parsePluginInteger(value);
        case 'secret':
            return value === '' ? null : value;
        default:
            return value.trim() === '' ? null : value;
    }
}
