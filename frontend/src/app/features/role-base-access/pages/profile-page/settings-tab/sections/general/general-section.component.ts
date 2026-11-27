import { Component, effect, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { TimezoneSelectorComponent } from '@shared/components';
import { GeneralPreferences } from '@shared/models';
import { normalizeIana } from '@shared/utils';

import { UserPreferencesService } from '../../../../../../../services/auth/user-preferences.service';
import { SettingsRowComponent } from '../../settings-section/settings-row.component';
import { SettingsSectionComponent } from '../../settings-section/settings-section.component';

type TimezonePreference = keyof GeneralPreferences;

/** Settings → General: the zone dates are shown in and the zone new schedule triggers start with. */
@Component({
    selector: 'app-general-section',
    templateUrl: './general-section.component.html',
    styleUrls: ['./general-section.component.scss'],
    imports: [ReactiveFormsModule, TimezoneSelectorComponent, SettingsSectionComponent, SettingsRowComponent],
})
export class GeneralSectionComponent {
    // Declared first: the fields below read it as they are created.
    private readonly preferencesService = inject(UserPreferencesService);

    private readonly general = this.preferencesService.section('general');

    /**
     * Shows the stored zones; `null`, a zone not chosen, shows as "Use browser timezone", so the user can tell it
     * follows the browser. Also brings a control back after a failed save.
     */
    private readonly showStoredZones = effect(() => {
        const general = this.general();
        this.form.setValue(
            {
                display_timezone: storedZone(general.display_timezone),
                default_timezone: storedZone(general.default_timezone),
            },
            { emitEvent: false }
        );
    });

    protected readonly form = new FormGroup({
        display_timezone: new FormControl<string | null>(null),
        default_timezone: new FormControl<string | null>(null),
    });

    constructor() {
        for (const preference of ['display_timezone', 'default_timezone'] as const) {
            this.form.controls[preference].valueChanges
                .pipe(takeUntilDestroyed())
                .subscribe((zone) => this.save(preference, zone));
        }
    }

    /** `zone` is `null` when "Use browser timezone" is picked: the preference is cleared. */
    private save(preference: TimezonePreference, zone: string | null): void {
        if (zone === storedZone(this.general()[preference])) return;
        this.preferencesService.patchSection('general', { [preference]: zone });
    }
}

function storedZone(preference: string | null): string | null {
    return preference === null ? null : normalizeIana(preference);
}
