import {
    PluginAction,
    PluginGrantState,
    PluginSignatureStatus,
    PluginState,
    PluginTrust,
} from '../models/plugin-admin.model';

/** How a badge reads at a glance. */
export type PluginBadgeTone = 'success' | 'warning' | 'danger' | 'neutral';

export const PLUGIN_ACTION_LABELS: Readonly<Record<PluginAction, string>> = {
    read: 'View',
    create: 'Create',
    update: 'Edit',
    delete: 'Delete',
    export: 'Export',
    use: 'Use',
};

export const PLUGIN_STATE_LABELS: Readonly<Record<PluginState, string>> = {
    uploaded: 'Awaiting review',
    provisioning: 'Provisioning',
    running: 'Running',
    failed: 'Failed',
    maintenance: 'Maintenance',
    uninstalling: 'Uninstalling',
    purging: 'Purging',
    removed: 'Removed',
};

export const PLUGIN_GRANT_STATE_LABELS: Readonly<Record<PluginGrantState, string>> = {
    granting: 'Granting',
    active: 'Active',
    install_failed: 'Install failed',
    upgrading: 'Upgrading',
    upgrade_failed: 'Upgrade failed',
    suspended: 'Suspended',
    purging: 'Purging',
};

export const PLUGIN_TRUST_LABELS: Readonly<Record<PluginTrust, string>> = {
    trusted: 'Trusted',
    untrusted: 'Untrusted',
};

export const PLUGIN_SIGNATURE_LABELS: Readonly<Record<PluginSignatureStatus, string>> = {
    valid: 'Signed by a trusted key',
    absent: 'Not signed',
    unknown_key: 'Signed by a key this deployment does not trust',
};

const PLUGIN_STATE_TONES: Readonly<Record<PluginState, PluginBadgeTone>> = {
    uploaded: 'warning',
    provisioning: 'neutral',
    running: 'success',
    failed: 'danger',
    maintenance: 'warning',
    uninstalling: 'neutral',
    purging: 'neutral',
    removed: 'neutral',
};

const PLUGIN_GRANT_STATE_TONES: Readonly<Record<PluginGrantState, PluginBadgeTone>> = {
    granting: 'neutral',
    active: 'success',
    install_failed: 'danger',
    upgrading: 'neutral',
    upgrade_failed: 'danger',
    suspended: 'warning',
    purging: 'neutral',
};

export function pluginStateTone(state: PluginState): PluginBadgeTone {
    return PLUGIN_STATE_TONES[state];
}

export function pluginGrantStateTone(state: PluginGrantState): PluginBadgeTone {
    return PLUGIN_GRANT_STATE_TONES[state];
}

export function pluginTrustTone(trust: PluginTrust): PluginBadgeTone {
    return trust === 'trusted' ? 'success' : 'danger';
}

/** The labels of a list of actions, in the order given: `View, Edit`. */
export function pluginActionLabels(actions: readonly PluginAction[]): string {
    return actions.map((action) => PLUGIN_ACTION_LABELS[action]).join(', ');
}
