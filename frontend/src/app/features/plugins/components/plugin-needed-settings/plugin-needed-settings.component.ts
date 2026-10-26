import { Component, input } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import {
    CustomInputComponent,
    SelectComponent,
    SelectItem,
    TextareaComponent,
    ToggleSwitchComponent,
} from '@shared/components';

import { PluginSettingNeeded } from '../../models/plugin-admin.model';
import {
    neededSettingProblem,
    PluginNeededSettingsForm,
    PluginSettingControlValue,
} from '../../utils/plugin-setting-value.util';

/** Why a new version needs a setting, under its control. */
const NEEDED_REASON_TEXTS: Readonly<Record<PluginSettingNeeded['reason'], string>> = {
    required: 'Required by this version, with no value or default yet.',
    invalid: 'The stored value is not valid for this version.',
};

/**
 * The settings a new version cannot start without, one control per type: enum → select, boolean → toggle, text →
 * textarea, secret → a password field that never shows a stored value, the rest a text input. The form belongs to the
 * container, which decides when every value is there.
 */
@Component({
    selector: 'app-plugin-needed-settings',
    imports: [CustomInputComponent, ReactiveFormsModule, SelectComponent, TextareaComponent, ToggleSwitchComponent],
    templateUrl: './plugin-needed-settings.component.html',
    styleUrl: './plugin-needed-settings.component.scss',
})
export class PluginNeededSettingsComponent {
    readonly settings = input.required<readonly PluginSettingNeeded[]>();
    readonly form = input.required<PluginNeededSettingsForm>();

    protected control(key: string): FormControl<PluginSettingControlValue> {
        return this.form().controls[key];
    }

    protected enumItems(setting: PluginSettingNeeded): SelectItem<string>[] {
        return (setting.values ?? []).map((value) => ({ name: value, value }));
    }

    protected fieldId(setting: PluginSettingNeeded): string {
        return `plugin-needed-setting-${setting.key}`;
    }

    protected reasonText(setting: PluginSettingNeeded): string {
        return NEEDED_REASON_TEXTS[setting.reason];
    }

    protected problem(setting: PluginSettingNeeded): string {
        return neededSettingProblem(setting, this.control(setting.key).value) ?? '';
    }
}
