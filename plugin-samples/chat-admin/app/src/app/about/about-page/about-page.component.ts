import { Component, computed, inject } from '@angular/core';
import { BRIDGE_VERSION } from '@epicstaff/plugin-sdk';

import { PluginBridgeService } from '../../core/plugin-bridge.service';

/** `/about`: what EpicStaff told the app at the handshake, and the live theme mode. */
@Component({
    selector: 'app-about-page',
    templateUrl: './about-page.component.html',
    styleUrl: './about-page.component.css',
})
export class AboutPageComponent {
    private readonly bridgeService = inject(PluginBridgeService);

    protected readonly context = this.bridgeService.context;
    protected readonly mocked = this.bridgeService.mocked;
    protected readonly themeMode = this.bridgeService.themeMode;
    protected readonly access = computed(() =>
        (this.context()?.access ?? []).map((entry) => ({
            alias: entry.alias,
            type: entry.type === 'key_value_table' ? 'Key-value table' : 'Flow',
            actions: entry.actions.join(', '),
        }))
    );

    protected readonly bridgeVersion = BRIDGE_VERSION;
}
