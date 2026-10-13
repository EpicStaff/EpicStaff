import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { RouteTab, RouteTabsComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';

@Component({
    selector: 'app-settings-page',
    templateUrl: './settings-page.component.html',
    styleUrls: ['./settings-page.component.scss'],
    imports: [RouterOutlet, RouteTabsComponent],
})
export class SettingsPageComponent {
    protected readonly tabs: RouteTab[] = [
        {
            routerLink: 'quickstart',
            icon: 'bolt',
            label: 'Quickstart',
            isPermitted: () => this.permissionsService.can(ResourceCode.LlmConfigs, ActionCode.Create),
        },
        {
            routerLink: 'default-llms',
            icon: 'robot',
            label: 'Default LLMs',
            isPermitted: () => this.permissionsService.can(ResourceCode.LlmConfigs, ActionCode.Read),
        },
        {
            routerLink: 'llm-library',
            icon: 'book',
            label: 'LLM Library',
            isPermitted: () => this.permissionsService.can(ResourceCode.LlmConfigs, ActionCode.Read),
        },
        {
            routerLink: 'webhook-triggers',
            iconClass: 'ti ti-webhook',
            label: 'Webhook Triggers',
            isPermitted: () => this.permissionsService.can(ResourceCode.Webhooks, ActionCode.Read),
        },
        {
            routerLink: 'voice',
            iconClass: 'ti ti-phone',
            label: 'Voice / Twilio',
            isPermitted: () => this.permissionsService.can(ResourceCode.Voice, ActionCode.Read),
        },
        {
            routerLink: 'secrets',
            icon: 'secrets',
            label: 'Secrets',
            isPermitted: () =>
                this.permissionsService.canAny(ResourceCode.Secrets, [ActionCode.Read, ActionCode.Create]),
        },
    ];

    private readonly permissionsService = inject(PermissionsService);
}
