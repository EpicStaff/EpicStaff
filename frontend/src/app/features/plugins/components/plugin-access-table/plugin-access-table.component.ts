import { Component, computed, input } from '@angular/core';

import { PluginDeclaredAccess } from '../../models/plugin-admin.model';
import { pluginActionLabels } from '../../utils/plugin-display.util';

/** The access a plugin declares to EpicStaff: each resource type, its actions and the plugin's reason. */
@Component({
    selector: 'app-plugin-access-table',
    templateUrl: './plugin-access-table.component.html',
    styleUrl: './plugin-access-table.component.scss',
})
export class PluginAccessTableComponent {
    readonly access = input.required<PluginDeclaredAccess[]>();

    protected readonly entries = computed(() =>
        this.access().map((entry) => ({ ...entry, actionLabels: pluginActionLabels(entry.actions) }))
    );
}
