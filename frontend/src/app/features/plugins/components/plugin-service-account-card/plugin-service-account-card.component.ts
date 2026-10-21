import { DatePipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { getRelativeTime } from '@shared/utils';

import { OrganizationServiceAccount } from '../../models/plugin-activity.model';
import { PLUGIN_GRANT_STATE_LABELS, pluginGrantStateTone } from '../../utils/plugin-display.util';
import { PluginAccessTableComponent } from '../plugin-access-table/plugin-access-table.component';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';
import { PluginIconComponent } from '../plugin-icon/plugin-icon.component';

/**
 * A plugin acting in the organization: its state, when its key was last used, the access it declared, the hosts its
 * backend may reach on the internet, and whether it keeps its data in a database of its own.
 */
@Component({
    selector: 'app-plugin-service-account-card',
    imports: [DatePipe, MatTooltip, PluginAccessTableComponent, PluginBadgeComponent, PluginIconComponent],
    templateUrl: './plugin-service-account-card.component.html',
    styleUrl: './plugin-service-account-card.component.scss',
})
export class PluginServiceAccountCardComponent {
    readonly account = input.required<OrganizationServiceAccount>();

    protected readonly stateLabel = computed(() => PLUGIN_GRANT_STATE_LABELS[this.account().grant_state]);
    protected readonly stateTone = computed(() => pluginGrantStateTone(this.account().grant_state));
    protected readonly keyLastUsed = computed(() => {
        const lastUsed = this.account().key_last_used_at;
        return lastUsed === null ? 'Never' : getRelativeTime(lastUsed);
    });
}
