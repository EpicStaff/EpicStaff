import { Component, computed, input, model } from '@angular/core';
import { CheckboxComponent } from '@shared/components';
import { formatFileSize } from '@shared/utils';

import { PluginAccessGrowth, PluginHookKind, PluginUpgradeReview } from '../../models/plugin-admin.model';
import { isPluginNumericLimitKey, PLUGIN_LIMIT_LABELS, pluginActionLabels } from '../../utils/plugin-display.util';
import { PluginAccessTableComponent } from '../plugin-access-table/plugin-access-table.component';

const HOOK_LABELS: Readonly<Record<PluginHookKind, string>> = {
    install: 'install',
    upgrade: 'upgrade',
    org_removed: 'organization removed',
};

const TRUST_CHANGE_TEXTS: Readonly<Record<PluginUpgradeReview['trust_change'], string | null>> = {
    none: null,
    became_untrusted: 'Unlike the installed version, this one is not signed by a key this deployment trusts.',
    became_trusted: 'Unlike the installed version, this one is signed by a key this deployment trusts.',
    signer_changed: 'This version is signed by a different trusted key than the installed one.',
};

/**
 * What upgrading the installed plugin to a pending package means: the version it comes from (and the failed upgrade it
 * replaces), the access it adds, which the SuperAdmin approves with a checkbox when the server asks for it, the other
 * changes, the backup taken first, the organizations that go offline, and whether Cancel stays possible. Everything
 * comes from the server's review; nothing here compares versions.
 */
@Component({
    selector: 'app-plugin-upgrade-review',
    imports: [CheckboxComponent, PluginAccessTableComponent],
    templateUrl: './plugin-upgrade-review.component.html',
    styleUrl: './plugin-upgrade-review.component.scss',
})
export class PluginUpgradeReviewComponent {
    readonly upgrade = input.required<PluginUpgradeReview>();
    readonly accessGrowth = input<PluginAccessGrowth | null>(null);
    readonly pluginName = input.required<string>();
    /** The checkbox is shown only while the package is pending. */
    readonly showAcknowledgement = input(false);
    readonly disabled = input(false);
    /** "I approve the new access" is ticked. */
    readonly growthAcknowledged = model(false);

    protected readonly fromText = computed(() => {
        const upgrade = this.upgrade();
        const replaces = upgrade.replaces_version
            ? ` · replaces the failed upgrade to ${upgrade.replaces_version}`
            : '';
        return `Upgrade from ${upgrade.from_version}${replaces}`;
    });
    protected readonly trustChangeText = computed(() => TRUST_CHANGE_TEXTS[this.upgrade().trust_change]);
    protected readonly hasGrowth = computed(() => {
        const growth = this.accessGrowth();
        if (!growth) return false;
        return (
            growth.requires_acknowledgement ||
            growth.access.length > 0 ||
            growth.outbound_hosts.length > 0 ||
            growth.public_paths.length > 0
        );
    });
    protected readonly growthComparedWith = computed(() => {
        const replaces = this.upgrade().replaces_version;
        return replaces ? `Compared with ${replaces}, the version this one replaces.` : null;
    });
    protected readonly publicPaths = computed(() =>
        (this.accessGrowth()?.public_paths ?? []).map((publicPath) => ({
            ...publicPath,
            matchLabel: publicPath.match === 'prefix' ? 'and below' : '',
            methodsLabel: publicPath.methods.join(', '),
            changeLabel: publicPath.change === 'new' ? 'New' : 'Widened',
        }))
    );
    /** "Migrations: 003_place_conditions.sql", "Hooks: upgrade (new)" and the like; empty when nothing else changes. */
    protected readonly changes = computed(() => changeLines(this.upgrade()));
    protected readonly backupText = computed(() => {
        const backup = this.upgrade().backup;
        if (!backup.required) return null;
        const name = backup.database_name ?? 'The database';
        const size =
            backup.database_size_bytes === null ? '' : ` (${formatFileSize(backup.database_size_bytes, 'auto')})`;
        return `${name}${size} is backed up before the migrations.`;
    });
    protected readonly offlineText = computed(() => {
        const count = this.upgrade().organizations_going_offline;
        if (count === 0) return null;
        return count === 1
            ? '1 organization is offline until its upgrade finishes.'
            : `${count} organizations are offline until their upgrade finishes.`;
    });
    protected readonly keepsRunningText = computed(() =>
        this.upgrade().maintenance ? null : `${this.pluginName()} is not stopped for this upgrade.`
    );
    protected readonly notCancellableText = computed(() =>
        this.upgrade().cancellable ? null : 'This upgrade cannot be cancelled once it starts.'
    );
}

function changeLines(upgrade: PluginUpgradeReview): string[] {
    const lines: string[] = [];
    if (upgrade.backend === 'added') lines.push('Backend: added. Each organization gets a service account for it.');
    if (upgrade.database === 'added') lines.push('Database: added, set up before the backend first starts.');
    if (upgrade.migrations_added.length > 0) lines.push(`Migrations: ${upgrade.migrations_added.join(', ')}`);
    const hooks = [
        ...upgrade.hooks_added.map((hook) => `${HOOK_LABELS[hook]} (new)`),
        ...upgrade.hooks_removed.map((hook) => `${HOOK_LABELS[hook]} (removed)`),
    ];
    if (hooks.length > 0) lines.push(`Hooks: ${hooks.join(', ')}`);
    const permissions = upgrade.user_permissions;
    const permissionParts = [
        permissions.added.length > 0 ? `added ${pluginActionLabels(permissions.added)}` : null,
        permissions.removed.length > 0 ? `removed ${pluginActionLabels(permissions.removed)}` : null,
        permissions.defaults_changed.length > 0
            ? `new defaults for ${pluginActionLabels(permissions.defaults_changed)}`
            : null,
    ].filter((part): part is string => part !== null);
    if (permissionParts.length > 0) lines.push(`Permissions for people: ${permissionParts.join('; ')}`);
    const settingParts = [
        upgrade.settings.added.length > 0 ? `added ${upgrade.settings.added.join(', ')}` : null,
        upgrade.settings.removed.length > 0 ? `removed ${upgrade.settings.removed.join(', ')}` : null,
    ].filter((part): part is string => part !== null);
    if (settingParts.length > 0) lines.push(`Settings: ${settingParts.join('; ')}`);
    if (upgrade.limits_changed.length > 0) {
        const limits = upgrade.limits_changed.map((key) =>
            isPluginNumericLimitKey(key) || key === 'cpu_priority' ? PLUGIN_LIMIT_LABELS[key] : key
        );
        lines.push(`Limits changed: ${limits.join(', ')}`);
    }
    return lines;
}
