import { DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigureModelsTabId } from '../../enums/configure-models-tab-id.enum';
import { ConfigureModelsTab } from '../../interfaces/configure-models-tab.interface';
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
export class ConfigureModelsDialogComponent implements OnInit {
    private readonly dialogRef: DialogRef<void> = inject(DialogRef<void>);
    private readonly permissionService = inject(PermissionsService);

    public readonly tabIds = ConfigureModelsTabId;
    public readonly tabs: ConfigureModelsTab[] = [
        {
            id: ConfigureModelsTabId.QUICKSTART,
            label: 'Quickstart',
            iconClass: 'ti ti-bolt',
            isPermitted: () => this.permissionService.can(ResourceCode.LlmConfigs, ActionCode.Create),
        },
        {
            id: ConfigureModelsTabId.DEFAULT_LLMS,
            label: 'Default LLMs',
            iconClass: 'ti ti-robot',
            isPermitted: () => this.permissionService.can(ResourceCode.LlmConfigs, ActionCode.Read),
        },
        {
            id: ConfigureModelsTabId.LLM_LIBRARY,
            label: 'LLM Library',
            iconClass: 'ti ti-books',
            isPermitted: () => this.permissionService.can(ResourceCode.LlmConfigs, ActionCode.Read),
        },
        {
            id: ConfigureModelsTabId.NGROK_CONFIG,
            label: 'Ngrok Configuration',
            iconClass: 'ti ti-cloud',
            isPermitted: () => this.permissionService.isSuperadmin,
        },
        {
            id: ConfigureModelsTabId.VOICE_SETTINGS,
            label: 'Voice / Twilio',
            iconClass: 'ti ti-phone',
            isPermitted: () => this.permissionService.isSuperadmin,
        },
    ];

    public readonly activeTabId = signal<ConfigureModelsTabId>(ConfigureModelsTabId.DEFAULT_LLMS);

    ngOnInit() {
        const canCreateConfigs = this.permissionService.can(ResourceCode.LlmConfigs, ActionCode.Create);
        this.activeTabId.set(canCreateConfigs ? ConfigureModelsTabId.QUICKSTART : ConfigureModelsTabId.DEFAULT_LLMS);
    }

    public selectTab(tabId: ConfigureModelsTabId): void {
        this.activeTabId.set(tabId);
    }

    public close(): void {
        this.dialogRef.close();
    }
}
