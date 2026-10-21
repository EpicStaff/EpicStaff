import { DatePipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { Spinner2Component } from '@shared/components';

import { PluginDetail, PluginPurgeProgress } from '../../models/plugin-admin.model';
import { PLUGIN_PURGE_NODE_LABELS, pluginDaysLeftText } from '../../utils/plugin-display.util';

/**
 * What an uninstalled or deleting plugin's page says above its tabs. Uninstalled: since when, and until when its data
 * is kept ("in 30 days"). Deleting: how far the deletion has come, as the server counts it (organizations left, data
 * removals waiting and failed, the plugin node). Nothing in any other state.
 */
@Component({
    selector: 'app-plugin-lifecycle-banner',
    imports: [DatePipe, Spinner2Component],
    templateUrl: './plugin-lifecycle-banner.component.html',
    styleUrl: './plugin-lifecycle-banner.component.scss',
})
export class PluginLifecycleBannerComponent {
    readonly plugin = input.required<PluginDetail>();

    protected readonly daysLeft = computed(() => {
        const purgeAfter = this.plugin().purge_after;
        return purgeAfter ? pluginDaysLeftText(purgeAfter) : null;
    });
    protected readonly progressText = computed(() => {
        const plugin = this.plugin();
        return purgeProgressText(plugin.name, plugin.purge_progress);
    });
}

/**
 * "Deleting Weather: 1 organization left · 1 data removal waiting · 0 failed · Plugin node: Waiting"; the node part
 * only for a plugin with a backend, with the node's error when it failed.
 */
function purgeProgressText(pluginName: string, progress: PluginPurgeProgress | null): string {
    if (!progress) return `Deleting ${pluginName}…`;
    const parts = [
        countText(progress.grants_left, 'organization left', 'organizations left'),
        countText(progress.data_removals_waiting, 'data removal waiting', 'data removals waiting'),
        `${progress.data_removals_failed} failed`,
    ];
    const node = PLUGIN_PURGE_NODE_LABELS[progress.node];
    if (node) {
        const error = progress.node === 'failed' && progress.node_error ? `: ${progress.node_error}` : '';
        parts.push(`Plugin node: ${node}${error}`);
    }
    return `Deleting ${pluginName}: ${parts.join(' · ')}`;
}

function countText(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`;
}
