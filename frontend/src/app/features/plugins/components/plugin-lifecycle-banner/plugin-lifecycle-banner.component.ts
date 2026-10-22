import { DatePipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { Spinner2Component } from '@shared/components';

import {
    PluginDetail,
    PluginPurgeProgress,
    PluginRestore,
    PluginUpgrade,
    PluginUpgradeStage,
} from '../../models/plugin-admin.model';
import {
    lowerFirst,
    PLUGIN_PURGE_NODE_LABELS,
    PLUGIN_RESTORE_STEP_LABELS,
    PLUGIN_UPGRADE_STEP_LABELS,
    pluginDaysLeftText,
} from '../../utils/plugin-display.util';

/** How a line of the banner reads at a glance. */
type BannerTone = 'progress' | 'offline' | 'failed' | 'done';

interface BannerLine {
    tone: BannerTone;
    text: string;
    /** What the node is doing, how long the plugin has been offline; `null` when there is nothing to add. */
    detail: string | null;
    /** Work still under way: a spinner leads the line. */
    working: boolean;
}

/** What a failure is said to have happened while doing, when the node named no step. */
const STAGE_ACTIVITIES: Readonly<Record<PluginUpgradeStage, string>> = {
    preparing: 'preparing the new version',
    maintenance: 'stopping the plugin',
    migrating: 'running migrations',
    done: 'finishing',
    cancelled: 'cancelling',
    abandoned: 'finishing',
};

/**
 * What a plugin's page says above its tabs, as the server reports it:
 * - uninstalled: since when, and until when its data is kept ("in 30 days");
 * - deleting: how far the deletion has come (organizations left, data removals waiting and failed, the plugin node);
 * - an open upgrade: preparing while the plugin keeps running, upgrading while it is offline (the node's step, for
 *   how long), or failed (while doing what, why, and whether the database already holds the new version's changes);
 *   and its latest restore while it is the latest news;
 * - after an upgrade, the organizations still upgrading and those whose upgrade failed;
 * - a refresh that failed, so the progress shown may be old.
 */
@Component({
    selector: 'app-plugin-lifecycle-banner',
    imports: [DatePipe, Spinner2Component],
    templateUrl: './plugin-lifecycle-banner.component.html',
    styleUrl: './plugin-lifecycle-banner.component.scss',
})
export class PluginLifecycleBannerComponent {
    readonly plugin = input.required<PluginDetail>();
    /** Why the last refresh failed; `null` when it did not. */
    readonly pollError = input<string | null>(null);

    protected readonly daysLeft = computed(() => {
        const purgeAfter = this.plugin().purge_after;
        return purgeAfter ? pluginDaysLeftText(purgeAfter) : null;
    });
    protected readonly progressText = computed(() => {
        const plugin = this.plugin();
        return purgeProgressText(plugin.name, plugin.purge_progress);
    });
    protected readonly upgradeLines = computed<BannerLine[]>(() => upgradeLines(this.plugin()));
    protected readonly hooksText = computed(() => {
        const plugin = this.plugin();
        const hooks = plugin.upgrade_hooks;
        if (plugin.open_upgrade || (hooks.upgrading === 0 && hooks.upgrade_failed === 0)) return null;
        return `Organizations upgrading: ${hooks.upgrading} · failed: ${hooks.upgrade_failed}`;
    });
    protected readonly staleText = computed(() => {
        const error = this.pollError();
        return error ? `Couldn't refresh: ${error.replace(/\.$/, '')}. Showing the last known progress.` : null;
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

function upgradeLines(plugin: PluginDetail): BannerLine[] {
    const upgrade = plugin.open_upgrade;
    if (!upgrade) return [];
    const version = upgrade.to_version;
    const restore = latestRestoreNews(upgrade);
    const lines: BannerLine[] = [];
    if (!upgrade.failed) {
        lines.push(workingLine(plugin, upgrade));
    } else if (restore?.state === 'succeeded') {
        lines.push({ tone: 'failed', text: `The upgrade to ${version} is stopped.`, detail: null, working: false });
    } else {
        const activity = upgrade.step
            ? lowerFirst(PLUGIN_UPGRADE_STEP_LABELS[upgrade.step])
            : STAGE_ACTIVITIES[upgrade.stage];
        const error = upgrade.last_error ?? 'no reason was given';
        lines.push({
            tone: 'failed',
            text: `The upgrade to ${version} failed while ${activity}: ${error}`,
            detail: null,
            working: false,
        });
        if (upgrade.database_changed) {
            lines.push({
                tone: 'failed',
                text: `The database already holds changes of ${version}. Restore the backup to go back.`,
                detail: null,
                working: false,
            });
        }
    }
    if (restore) lines.push(restoreLine(restore, version));
    return lines;
}

/** Preparing while the plugin keeps running, or upgrading while it is offline (or while it gets its first backend). */
function workingLine(plugin: PluginDetail, upgrade: PluginUpgrade): BannerLine {
    const version = upgrade.to_version;
    const step = upgrade.step ? PLUGIN_UPGRADE_STEP_LABELS[upgrade.step] : null;
    if (upgrade.stage === 'preparing') {
        return {
            tone: 'progress',
            text: `Preparing ${version} — ${plugin.name} keeps running`,
            detail: step,
            working: true,
        };
    }
    if (plugin.state !== 'maintenance') {
        return {
            tone: 'progress',
            text: `Upgrading to ${version} — ${plugin.name} keeps running`,
            detail: step,
            working: true,
        };
    }
    const since = upgrade.maintenance_started_at;
    const offline = since ? `offline for ${elapsedText(since)}` : null;
    const detail = [step, offline].filter((part): part is string => part !== null).join(' · ') || null;
    return { tone: 'offline', text: `Upgrading to ${version} — ${plugin.name} is offline`, detail, working: true };
}

/**
 * The upgrade's latest restore while it is news: under way, or finished after the upgrade's latest failure. A restore
 * from before a Retry that failed again is history.
 */
function latestRestoreNews(upgrade: PluginUpgrade): PluginRestore | null {
    const restore = upgrade.restore;
    if (!restore) return null;
    if (restore.state === 'pending' || restore.state === 'running') return restore;
    if (!restore.finished_at || !upgrade.failed_at) return null;
    return Date.parse(restore.finished_at) >= Date.parse(upgrade.failed_at) ? restore : null;
}

function restoreLine(restore: PluginRestore, version: string): BannerLine {
    const source =
        restore.backup.reason === 'pre_upgrade'
            ? `the backup taken before the upgrade to ${version}`
            : 'the backup taken before the last restore';
    switch (restore.state) {
        case 'pending':
        case 'running':
            return {
                tone: 'progress',
                text: `Restoring the database from ${source}`,
                detail: restore.step ? PLUGIN_RESTORE_STEP_LABELS[restore.step] : 'Waiting for the plugin node',
                working: true,
            };
        case 'succeeded':
            return { tone: 'done', text: `Database restored from ${source}`, detail: null, working: false };
        case 'failed': {
            const activity = restore.step ? ` while ${lowerFirst(PLUGIN_RESTORE_STEP_LABELS[restore.step])}` : '';
            const outcome =
                restore.pre_restore_backup_id === null
                    ? 'Nothing was changed.'
                    : 'Restore the backup taken before the restore to undo it.';
            return {
                tone: 'failed',
                text: `The restore failed${activity}: ${restore.last_error ?? 'no reason was given'}. ${outcome}`,
                detail: null,
                working: false,
            };
        }
    }
}

/** "less than a minute", "3 min", "1 h 5 min" since `since`. */
function elapsedText(since: string): string {
    const minutes = Math.floor(Math.max(0, Date.now() - Date.parse(since)) / 60_000);
    if (minutes < 1) return 'less than a minute';
    if (minutes < 60) return `${minutes} min`;
    const rest = minutes % 60;
    return rest === 0 ? `${Math.floor(minutes / 60)} h` : `${Math.floor(minutes / 60)} h ${rest} min`;
}
