import {
    PluginAction,
    PluginGrantAction,
    PluginGrantState,
    PluginSignatureStatus,
    PluginState,
    PluginTrust,
} from '../models/plugin-admin.model';
import {
    PluginCpuPriority,
    PluginDatabaseState,
    PluginDesiredState,
    PluginHealth,
    PluginLimitKey,
    PluginNumericLimitKey,
    PluginObservedState,
} from '../models/plugin-backend.model';
import {
    PluginDefaultModelSetting,
    PluginPreviewSessionStatus,
    PluginPreviewTriggerKind,
} from '../models/plugin-suspend-preview.model';

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
    granting: 'Installing',
    active: 'Active',
    install_failed: 'Install failed',
    upgrading: 'Upgrading',
    upgrade_failed: 'Upgrade failed',
    suspended: 'Suspended',
    purging: 'Purging',
};

/** The button of each grant action; "Suspend…" opens a dialog first. */
export const PLUGIN_GRANT_ACTION_LABELS: Readonly<Record<PluginGrantAction, string>> = {
    suspend: 'Suspend…',
    resume: 'Resume',
    retry_install: 'Retry install',
};

/** As the Default LLMs settings page names them; the page shows only the agent ones. */
export const PLUGIN_DEFAULT_MODEL_SETTING_LABELS: Readonly<Record<PluginDefaultModelSetting, string>> = {
    agent_llm_config: 'Agent LLM',
    agent_fcm_llm_config: 'Agent Function Calling LLM',
    voice_llm_config: 'Voice LLM',
    transcription_llm_config: 'Transcription LLM',
    project_manager_llm_config: 'Project Manager LLM',
    memory_embedding_config: 'Memory Embedding Model',
    memory_llm_config: 'Memory LLM',
};

/** The settings the Default LLMs settings page shows and can change; the others have no page. */
export const PLUGIN_DEFAULT_MODEL_SETTINGS_ON_SETTINGS_PAGE: ReadonlySet<PluginDefaultModelSetting> =
    new Set<PluginDefaultModelSetting>(['agent_llm_config', 'agent_fcm_llm_config']);

/** As the session lists name these statuses. */
export const PLUGIN_PREVIEW_SESSION_STATUS_LABELS: Readonly<Record<PluginPreviewSessionStatus, string>> = {
    pending: 'Pending',
    run: 'Running',
    wait_for_user: 'Waiting for User',
};

export const PLUGIN_PREVIEW_TRIGGER_KIND_LABELS: Readonly<Record<PluginPreviewTriggerKind, string>> = {
    schedule: 'Schedule',
    webhook: 'Webhook',
    telegram: 'Telegram',
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

export const PLUGIN_OBSERVED_STATE_LABELS: Readonly<Record<PluginObservedState, string>> = {
    unknown: 'Unknown',
    downloading: 'Downloading',
    building: 'Building',
    starting: 'Starting',
    running: 'Running',
    stopped: 'Stopped',
    failed: 'Failed',
};

const PLUGIN_OBSERVED_STATE_TONES: Readonly<Record<PluginObservedState, PluginBadgeTone>> = {
    unknown: 'neutral',
    downloading: 'neutral',
    building: 'neutral',
    starting: 'neutral',
    running: 'success',
    stopped: 'warning',
    failed: 'danger',
};

export const PLUGIN_DESIRED_STATE_LABELS: Readonly<Record<PluginDesiredState, string>> = {
    running: 'Running',
    stopped: 'Stopped',
};

export const PLUGIN_HEALTH_LABELS: Readonly<Record<PluginHealth, string>> = {
    ok: 'Healthy',
    failing: 'Failing',
    unknown: 'Unknown',
};

const PLUGIN_HEALTH_TONES: Readonly<Record<PluginHealth, PluginBadgeTone>> = {
    ok: 'success',
    failing: 'danger',
    unknown: 'neutral',
};

export const PLUGIN_CPU_PRIORITY_LABELS: Readonly<Record<PluginCpuPriority, string>> = {
    normal: 'Normal',
    low: 'Low',
};

export const PLUGIN_LIMIT_LABELS: Readonly<Record<PluginLimitKey, string>> = {
    memory_mb: 'Memory',
    db_connections: 'Database connections',
    statement_timeout_seconds: 'Statement timeout',
    requests_per_minute: 'Requests per minute',
    cpu_priority: 'CPU priority',
};

const PLUGIN_LIMIT_UNITS: Readonly<Record<PluginNumericLimitKey, string>> = {
    memory_mb: 'MB',
    db_connections: '',
    statement_timeout_seconds: 's',
    requests_per_minute: '/ min',
};

/** The limits of a plugin's database: they apply only to a plugin that has one. */
export const PLUGIN_DATABASE_LIMIT_KEYS: ReadonlySet<PluginLimitKey> = new Set<PluginLimitKey>([
    'db_connections',
    'statement_timeout_seconds',
]);

/** A limit's value with its unit: `256 MB`, `10 s`, `3`. */
export function formatPluginLimit(key: PluginNumericLimitKey, value: number): string {
    const unit = PLUGIN_LIMIT_UNITS[key];
    return unit ? `${value} ${unit}` : String(value);
}

export function isPluginNumericLimitKey(key: string): key is PluginNumericLimitKey {
    return Object.hasOwn(PLUGIN_LIMIT_UNITS, key);
}

export const PLUGIN_DATABASE_STATE_LABELS: Readonly<Record<PluginDatabaseState, string>> = {
    pending: 'Waiting for the node',
    provisioning: 'Setting up',
    ready: 'Ready',
    failed: 'Failed',
};

const PLUGIN_DATABASE_STATE_TONES: Readonly<Record<PluginDatabaseState, PluginBadgeTone>> = {
    pending: 'neutral',
    provisioning: 'neutral',
    ready: 'success',
    failed: 'danger',
};

export function pluginDatabaseStateTone(state: PluginDatabaseState): PluginBadgeTone {
    return PLUGIN_DATABASE_STATE_TONES[state];
}

export function pluginObservedStateTone(state: PluginObservedState): PluginBadgeTone {
    return PLUGIN_OBSERVED_STATE_TONES[state];
}

export function pluginHealthTone(health: PluginHealth): PluginBadgeTone {
    return PLUGIN_HEALTH_TONES[health];
}
