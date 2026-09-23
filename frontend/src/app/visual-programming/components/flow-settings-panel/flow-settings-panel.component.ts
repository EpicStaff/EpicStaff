import { DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, effect, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppIconComponent,
    AppSvgIconComponent,
    TimezoneSelectorComponent,
    ToggleSwitchComponent,
} from '@shared/components';

import { FlowSettingsService } from '../../services/flow-settings.service';

@Component({
    selector: 'app-flow-settings-panel',
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ReactiveFormsModule,
        ToggleSwitchComponent,
        TimezoneSelectorComponent,
        AppIconComponent,
        AppSvgIconComponent,
        MatTooltip,
    ],
    templateUrl: './flow-settings-panel.component.html',
    styleUrl: './flow-settings-panel.component.scss',
})
export class FlowSettingsPanelComponent {
    protected readonly flowSettings = inject(FlowSettingsService);
    protected readonly dialogRef = inject(DialogRef);

    protected readonly timezoneControl = new FormControl<string>(this.flowSettings.timezone(), { nonNullable: true });

    constructor() {
        effect(() => {
            this.timezoneControl.setValue(this.flowSettings.timezone(), { emitEvent: false });
        });
        this.timezoneControl.valueChanges
            .pipe(takeUntilDestroyed())
            .subscribe((tz) => this.flowSettings.timezone.set(tz));
    }
}
