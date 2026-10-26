import { formatDate } from '@angular/common';
import { formatFileSize } from '@shared/utils';

import {
    PluginActivityAction,
    PluginActivityDetailValue,
    PluginActivityEvent,
    PluginPurgeReason,
} from '../models/plugin-activity.model';
import { PluginBackupReason, PluginRestoreStep, PluginUpgradeStep } from '../models/plugin-admin.model';
import {
    formatPluginLimit,
    isPluginNumericLimitKey,
    lowerFirst,
    PLUGIN_BACKUP_REASON_LABELS,
    PLUGIN_CPU_PRIORITY_LABELS,
    PLUGIN_LIMIT_LABELS,
    PLUGIN_RESTORE_STEP_LABELS,
    PLUGIN_UPGRADE_STEP_LABELS,
} from './plugin-display.util';

/** How each activity action reads in a list. A new action needs its label here before it builds. */
export const PLUGIN_ACTIVITY_ACTION_LABELS: Readonly<Record<PluginActivityAction, string>> = {
    api_request: 'API request',
    package_approved: 'Package approved',
    grant_created: 'Granted',
    install_hook_succeeded: 'Install succeeded',
    install_hook_failed: 'Install failed',
    install_hook_retried: 'Install retried',
    settings_changed: 'Settings changed',
    limits_changed: 'Limits changed',
    restarted: 'Restarted',
    grant_suspended: 'Suspended in this organization',
    grant_resumed: 'Resumed in this organization',
    database_ready: 'Database ready',
    database_failed: 'Database setup failed',
    database_limit_restored: 'Database timeout restored',
    plugin_uninstalled: 'Uninstalled',
    plugin_reinstalled: 'Reinstalled',
    plugin_purge_started: 'Deletion started',
    plugin_removal_failed: 'Removal from the node failed',
    plugin_removal_retried: 'Removal retried',
    plugin_purged: 'Deleted',
    grant_purge_started: 'Data deletion started',
    grant_purged: 'Data deleted',
    org_removed_hook_succeeded: 'Data removal done',
    org_removed_hook_failed: 'Data removal failed',
    org_removed_hook_retried: 'Data removal retried',
    org_removed_hook_skipped: 'Data removal skipped',
    plugin_upgrade_started: 'Upgrade started',
    plugin_maintenance_started: 'Maintenance started',
    plugin_upgrade_failed: 'Upgrade failed',
    plugin_upgrade_retried: 'Upgrade retried',
    plugin_upgrade_cancelled: 'Upgrade cancelled',
    plugin_upgraded: 'Upgraded',
    database_backed_up: 'Database backed up',
    database_restore_requested: 'Database restore requested',
    database_restored: 'Database restored',
    database_restore_failed: 'Database restore failed',
    upgrade_hook_succeeded: 'Upgrade hook succeeded',
    upgrade_hook_failed: 'Upgrade hook failed',
    upgrade_hook_retried: 'Upgrade hook retried',
    development_target_set: 'Development started or changed',
    development_target_cleared: 'Development stopped',
    development_runtime_file_issued: 'Development runtime file downloaded',
};

/** Why a deletion began, as `detail.reason` says. */
export const PLUGIN_PURGE_REASON_LABELS: Readonly<Record<PluginPurgeReason, string>> = {
    requested: 'Requested',
    grace_period_over: 'Grace period over',
    plugin_deleted: 'Plugin deleted',
};

/** The actions whose `detail.error` says what went wrong. */
const ACTIONS_WITH_ERROR: ReadonlySet<PluginActivityAction> = new Set<PluginActivityAction>([
    'install_hook_failed',
    'database_failed',
    'plugin_removal_failed',
    'org_removed_hook_failed',
    'plugin_upgrade_failed',
    'upgrade_hook_failed',
    'database_restore_failed',
]);

/** The actions whose `detail.reason` says why a deletion began. */
const ACTIONS_WITH_REASON: ReadonlySet<PluginActivityAction> = new Set<PluginActivityAction>([
    'grant_purge_started',
    'plugin_purge_started',
]);

/**
 * Who did it: the plugin ("Weather (plugin)"), a SuperAdmin ("ada@example.com (SuperAdmin)") or EpicStaff itself
 * ("Platform"), followed by "on behalf of <email>" when the plugin acted for a person.
 */
export function pluginActivityActorText(event: PluginActivityEvent): string {
    const actor = actorLabel(event);
    return event.on_behalf_of ? `${actor} on behalf of ${event.on_behalf_of.label}` : actor;
}

/** `POST /api/run-session/ (201)` for an API request; `null` for every other action. */
export function pluginActivityRequestLine(event: PluginActivityEvent): string | null {
    const request = event.request;
    return request ? `${request.method} ${request.path} (${request.status})` : null;
}

/** What the event was about: its name when known, else its type and id; `null` when unknown. */
export function pluginActivityTargetText(event: PluginActivityEvent): string | null {
    const target = event.target;
    if (!target) return null;
    if (target.label) return target.label;
    if (target.id === null) return null;
    return target.resource_type ? `${target.resource_type} ${target.id}` : target.id;
}

/** The organization's name, its id once it is deleted, or that the event concerns the whole deployment. */
export function pluginActivityOrganizationText(event: PluginActivityEvent): string {
    const organization = event.organization;
    if (!organization) return 'Whole deployment';
    return organization.name ?? `Organization #${organization.id} (deleted)`;
}

export function pluginActivityPluginText(event: PluginActivityEvent): string {
    return event.plugin.name ?? event.plugin.identifier;
}

/**
 * The error of a failed install, database setup, removal from the node, data removal, upgrade, upgrade hook or
 * restore, as the hook or the node reported it; else `null`.
 */
export function pluginActivityErrorText(event: PluginActivityEvent): string | null {
    if (!ACTIONS_WITH_ERROR.has(event.action)) return null;
    const error = event.detail['error'];
    return typeof error === 'string' && error ? error : null;
}

/**
 * The overrides in force after a limits change (`Overrides: Memory 128 MB, CPU priority Low`), why a deletion began
 * (`Reason: Grace period over`), the versions and backups of an upgrade event (`0.6.0 → 0.7.0 · offline 2 min`), or
 * what a development event changed (`Backend port 8001 · Frontend dev server port 5173`); else `null`. `locale` formats
 * the time of a planned retry.
 */
export function pluginActivityDetailText(event: PluginActivityEvent, locale: string): string | null {
    if (event.action === 'limits_changed') {
        const overrides = Object.entries(event.detail).map(([key, value]) => limitOverrideText(key, value));
        return `Overrides: ${overrides.length > 0 ? overrides.join(', ') : 'none'}`;
    }
    if (ACTIONS_WITH_REASON.has(event.action)) return reasonText(event.detail['reason']);
    return developmentDetailText(event) ?? upgradeDetailText(event, locale);
}

/** A plugin request answered for a development backend, with a development key: marked "Development" in a list. */
export function pluginActivityIsDevelopment(event: PluginActivityEvent): boolean {
    return event.action === 'api_request' && event.detail['development'] === true;
}

/** What a development event adds to its label; `null` for any other event. */
function developmentDetailText(event: PluginActivityEvent): string | null {
    const detail = event.detail;
    switch (event.action) {
        case 'development_target_set': {
            const backendPort = detail['backend_port'];
            const spaPort = detail['spa_port'];
            return joined([
                typeof backendPort === 'number' ? `Backend port ${backendPort}` : null,
                typeof spaPort === 'number' ? `Frontend dev server port ${spaPort}` : null,
            ]);
        }
        case 'development_target_cleared': {
            const revoked = detail['revoked_keys'];
            if (typeof revoked !== 'number' || revoked <= 0) return null;
            return `${revoked} development ${revoked === 1 ? 'key' : 'keys'} stopped`;
        }
        case 'development_runtime_file_issued': {
            const organizations = detail['organizations'];
            if (typeof organizations !== 'number') return null;
            return `For ${organizations} ${organizations === 1 ? 'organization' : 'organizations'}`;
        }
        default:
            return null;
    }
}

/** What an upgrade, backup, restore or upgrade hook event adds to its label; `null` for any other event. */
function upgradeDetailText(event: PluginActivityEvent, locale: string): string | null {
    const detail = event.detail;
    const from = detailText(detail['from_version']);
    const to = detailText(detail['to_version']);
    switch (event.action) {
        case 'plugin_upgrade_started': {
            const replaced = detailText(detail['replaced_version']);
            return joined([versionsText(from, to), replaced ? `replaces ${replaced}` : null]);
        }
        case 'plugin_upgraded': {
            const seconds = detail['maintenance_seconds'];
            const offline = typeof seconds === 'number' && seconds > 0 ? `offline ${durationText(seconds)}` : null;
            return joined([versionsText(from, to), offline]);
        }
        case 'plugin_maintenance_started': {
            const organizations = detail['organizations'];
            const offline =
                typeof organizations === 'number'
                    ? `${organizations} ${organizations === 1 ? 'organization' : 'organizations'} offline`
                    : null;
            return joined([to ? `To ${to}` : null, offline]);
        }
        case 'plugin_upgrade_retried':
        case 'plugin_upgrade_cancelled':
            return to ? `To ${to}` : null;
        case 'plugin_upgrade_failed': {
            const step = detailText(detail['step']);
            const where = step && isUpgradeStep(step) ? `while ${lowerFirst(PLUGIN_UPGRADE_STEP_LABELS[step])}` : null;
            return joined([to ? `To ${to}` : null, where]);
        }
        case 'database_backed_up':
            return backupDetailText(detail);
        case 'database_restore_requested':
        case 'database_restored': {
            const file = detailText(detail['file_name']);
            return file ? `From ${file}` : null;
        }
        case 'database_restore_failed': {
            const step = detailText(detail['step']);
            return step && isRestoreStep(step) ? `While ${lowerFirst(PLUGIN_RESTORE_STEP_LABELS[step])}` : null;
        }
        case 'upgrade_hook_succeeded':
            return from ? `From ${from}${to ? ` to ${to}` : ''}` : null;
        case 'upgrade_hook_failed': {
            const next = detailText(detail['next_attempt_at']);
            return next ? `Next try ${formatDate(next, 'shortTime', locale)}` : 'No retries left: Retry it on its row';
        }
        default:
            return null;
    }
}

/** "Before upgrade · holds 0.6.0 · 7.3 MB". */
function backupDetailText(detail: PluginActivityEvent['detail']): string | null {
    const reason = detailText(detail['reason']);
    const version = detailText(detail['version']);
    const size = detail['size_bytes'];
    return joined([
        reason && isBackupReason(reason) ? PLUGIN_BACKUP_REASON_LABELS[reason] : null,
        version ? `holds ${version}` : null,
        typeof size === 'number' ? formatFileSize(size, 'auto') : null,
    ]);
}

function versionsText(from: string | null, to: string | null): string | null {
    if (from && to) return `${from} → ${to}`;
    return to ? `To ${to}` : null;
}

/** "45 s", "3 min", "1 h 5 min". */
function durationText(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)} s`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min`;
    const rest = minutes % 60;
    return rest === 0 ? `${Math.floor(minutes / 60)} h` : `${Math.floor(minutes / 60)} h ${rest} min`;
}

/** The parts that are there, joined with " · "; `null` when none is. */
function joined(parts: readonly (string | null)[]): string | null {
    const present = parts.filter((part): part is string => part !== null && part !== '');
    return present.length > 0 ? present.join(' · ') : null;
}

function detailText(value: PluginActivityDetailValue | undefined): string | null {
    return typeof value === 'string' && value ? value : null;
}

function isUpgradeStep(step: string): step is PluginUpgradeStep {
    return Object.hasOwn(PLUGIN_UPGRADE_STEP_LABELS, step);
}

function isRestoreStep(step: string): step is PluginRestoreStep {
    return Object.hasOwn(PLUGIN_RESTORE_STEP_LABELS, step);
}

function isBackupReason(reason: string): reason is PluginBackupReason {
    return Object.hasOwn(PLUGIN_BACKUP_REASON_LABELS, reason);
}

/** A reason this page does not know shows as the server sent it; a missing one shows nothing. */
function reasonText(reason: PluginActivityDetailValue | undefined): string | null {
    if (typeof reason !== 'string' || !reason) return null;
    const label = isPurgeReason(reason) ? PLUGIN_PURGE_REASON_LABELS[reason] : reason;
    return `Reason: ${label}`;
}

function isPurgeReason(reason: string): reason is PluginPurgeReason {
    return Object.hasOwn(PLUGIN_PURGE_REASON_LABELS, reason);
}

/** A limit as the limits form names it; a key this page does not know as the server sent it. */
function limitOverrideText(key: string, value: PluginActivityDetailValue): string {
    if (isPluginNumericLimitKey(key) && typeof value === 'number') {
        return `${PLUGIN_LIMIT_LABELS[key]} ${formatPluginLimit(key, value)}`;
    }
    if (key === 'cpu_priority' && (value === 'low' || value === 'normal')) {
        return `${PLUGIN_LIMIT_LABELS.cpu_priority} ${PLUGIN_CPU_PRIORITY_LABELS[value]}`;
    }
    return `${key} ${String(value)}`;
}

function actorLabel(event: PluginActivityEvent): string {
    switch (event.actor.kind) {
        case 'superadmin':
            return `${event.actor.label} (SuperAdmin)`;
        case 'platform':
            return 'Platform';
        case 'plugin':
            return event.actor.label;
    }
}
