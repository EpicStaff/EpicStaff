import { Component, computed, input } from '@angular/core';
import { Spinner2Component } from '@shared/components';

/**
 * What a person sees instead of a plugin's page while the plugin, or their organization's install of it, is being
 * updated. The host page checks again by itself and opens the plugin once it is back.
 */
@Component({
    selector: 'app-plugin-maintenance-panel',
    imports: [Spinner2Component],
    templateUrl: './plugin-maintenance-panel.component.html',
    styleUrl: './plugin-maintenance-panel.component.scss',
})
export class PluginMaintenancePanelComponent {
    readonly pluginName = input.required<string>();

    protected readonly message = computed(
        () => `${this.pluginName()} is being updated. It will be back in a few minutes.`
    );
}
