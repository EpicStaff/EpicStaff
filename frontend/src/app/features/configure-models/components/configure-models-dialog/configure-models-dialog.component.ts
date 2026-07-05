import { DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { CONFIGURE_MODELS_TABS } from '../../constants/configure-models-tabs.constant';
import { ConfigureModelsTabId } from '../../enums/configure-models-tab-id.enum';
import { DefaultLlmsSectionComponent } from '../default-llms-section/default-llms-section.component';
import { LlmLibrarySectionComponent } from '../llm-library-section/llm-library-section.component';
import { AppNgrokSectionComponent } from '../ngrok-config-section/ngrok-config-section.component';
import { QuickstartSectionComponent } from '../quickstart-section/quickstart-section.component';
import { VoiceSettingsSectionComponent } from '../voice-settings-section/voice-settings-section.component';

@Component({
    selector: 'app-configure-models-dialog',
    imports: [
        CommonModule,
        DefaultLlmsSectionComponent,
        QuickstartSectionComponent,
        LlmLibrarySectionComponent,
        AppNgrokSectionComponent,
        VoiceSettingsSectionComponent,
        AppSvgIconComponent,
        MatTooltipModule,
    ],
    templateUrl: './configure-models-dialog.component.html',
    styleUrls: ['./configure-models-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConfigureModelsDialogComponent {
    private readonly dialogRef: DialogRef<void> = inject(DialogRef<void>);

    public readonly tabIds = ConfigureModelsTabId;
    public readonly tabs = CONFIGURE_MODELS_TABS;

    public readonly activeTabId = signal<ConfigureModelsTabId>(ConfigureModelsTabId.QUICKSTART);

    public selectTab(tabId: ConfigureModelsTabId): void {
        this.activeTabId.set(tabId);
    }

    public close(): void {
        this.dialogRef.close();
    }
}
