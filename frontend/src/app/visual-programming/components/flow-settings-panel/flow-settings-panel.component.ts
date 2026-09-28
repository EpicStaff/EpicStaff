import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, effect, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppIconComponent,
    AppSvgIconComponent,
    TimezoneSelectorComponent,
    ToggleSwitchComponent,
} from '@shared/components';

import { FlowReadOnlyService } from '../../services/flow-readonly.service';
import { FlowSettingsService } from '../../services/flow-settings.service';

export interface FlowSettingsPanelData {
    /** Version preview: nodes cannot be added, so the default timezone for new ones is locked. */
    readOnly?: boolean;
}

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
    private readonly flowReadOnly = inject(FlowReadOnlyService);
    private readonly isPreview =
        inject<FlowSettingsPanelData | null>(DIALOG_DATA, { optional: true })?.readOnly ?? false;
    /** Version preview (dialog data) or a Viewer (no Flows:Update). */
    protected readonly isReadOnly = computed(() => this.isPreview || this.flowReadOnly.isReadOnly());

    protected readonly timezoneControl = new FormControl<string>(this.flowSettings.timezone(), { nonNullable: true });

    constructor() {
        if (this.isReadOnly()) {
            this.timezoneControl.disable({ emitEvent: false });
        }
        effect(() => {
            this.timezoneControl.setValue(this.flowSettings.timezone(), { emitEvent: false });
        });
        this.timezoneControl.valueChanges
            .pipe(takeUntilDestroyed())
            .subscribe((tz) => this.flowSettings.timezone.set(tz));
    }
}
