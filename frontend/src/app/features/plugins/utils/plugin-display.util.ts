import { formatDate } from '@angular/common';
import { daysUntil } from '@shared/utils';

import {
    PluginAction,
    PluginBackup,
    PluginBackupReason,
    PluginGrant,
    PluginGrantAction,
    PluginGrantState,
    PluginHookJobState,
    PluginLifecycleAction,
    PluginOrgRemovedJob,
    PluginOrgRemovedJobAction,
    PluginPendingPackage,
    PluginPurgeNodeState,
    PluginRestoreStep,
    PluginSignatureStatus,
    PluginState,
    PluginSummary,
    PluginTrust,
    PluginUpgradeStep,
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
    uninstalling: 'Uninstalled',
    purging: 'Deleting',
};

/** The header button of each plugin action; those ending in "…" open a dialog first. */
export const PLUGIN_LIFECYCLE_ACTION_LABELS: Readonly<Record<PluginLifecycleAction, string>> = {
    uninstall: 'Uninstall…',
    reinstall: 'Reinstall',
    purge: 'Delete permanently…',
    retry_removal: 'Retry removal',
    upgrade: 'Upgrade…',
    cancel_upgrade: 'Cancel upgrade',
    retry_upgrade: 'Retry',
    restore_backup: 'Restore backup…',
};

/** A header button's label; "Upgrade to 0.7.0…" names the version waiting for review. */
export function pluginLifecycleActionLabel(
    action: PluginLifecycleAction,
    pendingPackage: PluginPendingPackage | null
): string {
    if (action === 'upgrade' && pendingPackage) return `Upgrade to ${pendingPackage.version}…`;
    return PLUGIN_LIFECYCLE_ACTION_LABELS[action];
}

/** What the plugin node is doing at each step of an upgrade. Lower-cased, it ends "The upgrade failed while …". */
export const PLUGIN_UPGRADE_STEP_LABELS: Readonly<Record<PluginUpgradeStep, string>> = {
    download: 'Downloading the package',
    verify: 'Verifying the package',
    build: 'Building the new version',
    drain: 'Waiting for running hooks to finish',
    stop: 'Stopping the plugin',
    backup: 'Backing up the database',
    migrate: 'Running migrations',
    start: 'Starting the new version',
};

/** What the plugin node is doing at each step of a restore. Lower-cased, it ends "The restore failed while …". */
export const PLUGIN_RESTORE_STEP_LABELS: Readonly<Record<PluginRestoreStep, string>> = {
    verify: 'Checking the backup',
    backup: 'Backing up the current database',
    close: 'Closing the connections',
    recreate: 'Recreating the database',
    restore: 'Restoring the backup',
    settings: 'Restoring the database settings',
    assert: 'Checking the database',
};

export const PLUGIN_BACKUP_REASON_LABELS: Readonly<Record<PluginBackupReason, string>> = {
    pre_upgrade: 'Before upgrade',
    pre_restore: 'Before restore',
};

/** Why a backup cannot be restored, after "Not restorable: ". */
export const PLUGIN_BACKUP_NOT_RESTORABLE_LABELS: Readonly<
    Record<NonNullable<PluginBackup['not_restorable_reason']>, string>
> = {
    earlier_upgrade: 'from an earlier upgrade',
    not_now: 'not while the upgrade runs or a restore is under way',
    mismatch: 'its file changed on the plugin node',
};

/** "Before upgrade to 0.7.0" or "Before restore · during the upgrade to 0.7.1"; without the version when unknown. */
export function pluginBackupTitle(backup: Pick<PluginBackup, 'reason' | 'upgrade'>): string {
    const toVersion = backup.upgrade?.to_version;
    if (!toVersion) return PLUGIN_BACKUP_REASON_LABELS[backup.reason];
    return backup.reason === 'pre_upgrade'
        ? `Before upgrade to ${toVersion}`
        : `Before restore · during the upgrade to ${toVersion}`;
}

/**
 * The plugin list's badge for an open upgrade: "Preparing 0.7.0", "Upgrading to 0.7.0" (while the plugin keeps
 * running, as when a version adds its first backend) or "Upgrade failed"; `null` without one, and while the plugin is
 * in maintenance, which its state badge says.
 */
export function pluginUpgradeBadge(
    plugin: Pick<PluginSummary, 'state' | 'upgrade'>
): { label: string; tone: PluginBadgeTone } | null {
    const upgrade = plugin.upgrade;
    if (!upgrade) return null;
    if (upgrade.failed) return { label: 'Upgrade failed', tone: 'danger' };
    if (upgrade.stage === 'preparing') return { label: `Preparing ${upgrade.to_version}`, tone: 'neutral' };
    if (plugin.state === 'maintenance') return null;
    return { label: `Upgrading to ${upgrade.to_version}`, tone: 'neutral' };
}

/** A sentence's first letter lower-cased, so a label can follow "while". */
export function lowerFirst(text: string): string {
    return text.charAt(0).toLowerCase() + text.slice(1);
}

export const PLUGIN_GRANT_STATE_LABELS: Readonly<Record<PluginGrantState, string>> = {
    granting: 'Installing',
    active: 'Active',
    install_failed: 'Install failed',
    upgrading: 'Upgrading',
    upgrade_failed: 'Upgrade failed',
    suspended: 'Suspended',
    purging: 'Deleting data',
};

/** The grant's state as the grants table names it; a grant suspended by an uninstall says so. */
export function pluginGrantStateLabel(grant: Pick<PluginGrant, 'state' | 'suspension_cause'>): string {
    if (grant.state === 'suspended' && grant.suspension_cause === 'uninstall') return 'Suspended (plugin uninstalled)';
    return PLUGIN_GRANT_STATE_LABELS[grant.state];
}

/** The button of each grant action; those ending in "…" open a dialog first. */
export const PLUGIN_GRANT_ACTION_LABELS: Readonly<Record<PluginGrantAction, string>> = {
    suspend: 'Suspend…',
    resume: 'Resume',
    retry_install: 'Retry install',
    retry_upgrade: 'Retry upgrade',
    purge: 'Delete data…',
};

/** A data removal's state, as the grants table and the deleted organizations list name it. */
export const PLUGIN_DATA_REMOVAL_STATE_LABELS: Readonly<Record<PluginHookJobState, string>> = {
    pending: 'Waiting',
    running: 'Running',
    succeeded: 'Done',
    failed: 'Failed',
    skipped: 'Skipped',
};

const PLUGIN_DATA_REMOVAL_STATE_TONES: Readonly<Record<PluginHookJobState, PluginBadgeTone>> = {
    pending: 'neutral',
    running: 'neutral',
    succeeded: 'success',
    failed: 'danger',
    skipped: 'warning',
};

export function pluginDataRemovalStateTone(state: PluginHookJobState): PluginBadgeTone {
    return PLUGIN_DATA_REMOVAL_STATE_TONES[state];
}

export const PLUGIN_DATA_REMOVAL_ACTION_LABELS: Readonly<Record<PluginOrgRemovedJobAction, string>> = {
    retry: 'Retry',
    skip: 'Skip',
};

/** How a deleting row tells where the plugin is with deleting its own data in the organization. */
export interface PluginDataRemovalLine {
    job: PluginOrgRemovedJob;
    message: string;
    /** "Attempt 2 · next try 10:42"; `null` when there is nothing to add. */
    progress: string | null;
    /** The error of the last failed attempt while the job retries by itself. */
    lastError: string | null;
    failed: boolean;
}

/** Nothing for a grant without a data removal, or once the plugin has finished or skipped it. */
export function pluginDataRemovalLine(
    job: PluginOrgRemovedJob | null,
    pluginName: string,
    locale: string
): PluginDataRemovalLine | null {
    if (!job) return null;
    switch (job.state) {
        case 'pending':
        case 'running':
            return {
                job,
                message: `${pluginName} is deleting its data`,
                progress: pluginRetryProgress(job, locale),
                lastError: job.error,
                failed: false,
            };
        case 'failed':
            return {
                job,
                message: `${pluginName} could not delete its data: ${job.error ?? 'no reason was given'}`,
                progress: null,
                lastError: null,
                failed: true,
            };
        case 'succeeded':
        case 'skipped':
            return null;
    }
}

/**
 * "Attempt 2 · next try 10:42" for a hook that tries again by itself: the attempt once one was made, the next try
 * while one is planned; `null` when there is nothing to say.
 */
export function pluginRetryProgress(
    job: { state: PluginHookJobState; attempt: number; next_attempt_at: string | null },
    locale: string
): string | null {
    const parts: string[] = [];
    if (job.attempt > 0) parts.push(`Attempt ${job.attempt}`);
    if (job.state === 'pending' && job.next_attempt_at) {
        parts.push(`next try ${formatDate(job.next_attempt_at, 'shortTime', locale)}`);
    }
    return parts.length > 0 ? parts.join(' · ') : null;
}

/** The organization of a data removal: its name when the job was made, marked once the organization is deleted. */
export function pluginDataRemovalOrganizationText(job: PluginOrgRemovedJob): string {
    return job.organization.exists ? job.organization.name : `${job.organization.name} (deleted)`;
}

/** Where the plugin node is with a plugin being deleted; `null` when the plugin has no backend. */
export const PLUGIN_PURGE_NODE_LABELS: Readonly<Record<PluginPurgeNodeState, string | null>> = {
    waiting: 'Waiting',
    removing: 'Removing',
    failed: 'Failed',
    not_needed: null,
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
    uninstalling: 'warning',
    purging: 'danger',
};

const PLUGIN_GRANT_STATE_TONES: Readonly<Record<PluginGrantState, PluginBadgeTone>> = {
    granting: 'neutral',
    active: 'success',
    install_failed: 'danger',
    upgrading: 'neutral',
    upgrade_failed: 'danger',
    suspended: 'warning',
    purging: 'danger',
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

/** A plugin's trust as its badge names it; "No package" for a plugin that has none left. */
export function pluginTrustLabel(trust: PluginTrust | null): string {
    return trust ? PLUGIN_TRUST_LABELS[trust] : 'No package';
}

export function pluginTrustBadgeTone(trust: PluginTrust | null): PluginBadgeTone {
    return trust ? pluginTrustTone(trust) : 'neutral';
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

/** How long until a date, in whole calendar days: `in 30 days`, `in 1 day`; `today` once the day has come. */
export function pluginDaysLeftText(date: string): string {
    const days = daysUntil(date);
    if (days <= 0) return 'today';
    return days === 1 ? 'in 1 day' : `in ${days} days`;
}
