import { DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, effect, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppIconComponent,
    AppSvgIconComponent,
    ButtonComponent,
    TimezoneSelectorComponent,
    ToggleSwitchComponent,
} from '@shared/components';

import { FlowSettingsService } from '../../services/flow-settings.service';

/**
 * The open flow's view settings, for the signed-in user only: a change here overrides their account's flow editor
 * preferences for this flow and changes nothing for anybody else, so a read-only user may change them too.
 */
@Component({
    selector: 'app-flow-settings-panel',
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ReactiveFormsModule,
        ToggleSwitchComponent,
        TimezoneSelectorComponent,
        AppIconComponent,
        AppSvgIconComponent,
        ButtonComponent,
        MatTooltip,
    ],
    templateUrl: './flow-settings-panel.component.html',
    styleUrl: './flow-settings-panel.component.scss',
})
export class FlowSettingsPanelComponent {
    protected readonly flowSettings = inject(FlowSettingsService);
    protected readonly dialogRef = inject(DialogRef);

    /** The flow's own zone for new schedule triggers; `null` follows the account's default timezone. */
    protected readonly scheduleZoneControl = new FormControl<string | null>(this.flowSettings.flowScheduleZone());

    constructor() {
        // The override arrives after the panel may have opened, and a failed save rolls it back.
        effect(() => this.scheduleZoneControl.setValue(this.flowSettings.flowScheduleZone(), { emitEvent: false }));
        this.scheduleZoneControl.valueChanges
            .pipe(takeUntilDestroyed())
            .subscribe((zone) => this.flowSettings.setForCurrentFlow({ default_timezone: zone }));
    }
}
