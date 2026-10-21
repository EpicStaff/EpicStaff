import {
    PluginActivityAction,
    PluginActivityDetailValue,
    PluginActivityEvent,
    PluginPurgeReason,
} from '../models/plugin-activity.model';
import {
    formatPluginLimit,
    isPluginNumericLimitKey,
    PLUGIN_CPU_PRIORITY_LABELS,
    PLUGIN_LIMIT_LABELS,
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
 * The error of a failed install, database setup, removal from the node or data removal, as the hook or the node
 * reported it; else `null`.
 */
export function pluginActivityErrorText(event: PluginActivityEvent): string | null {
    if (!ACTIONS_WITH_ERROR.has(event.action)) return null;
    const error = event.detail['error'];
    return typeof error === 'string' && error ? error : null;
}

/**
 * The overrides in force after a limits change (`Overrides: Memory 128 MB, CPU priority Low`), or why a deletion began
 * (`Reason: Grace period over`); else `null`.
 */
export function pluginActivityDetailText(event: PluginActivityEvent): string | null {
    if (event.action === 'limits_changed') {
        const overrides = Object.entries(event.detail).map(([key, value]) => limitOverrideText(key, value));
        return `Overrides: ${overrides.length > 0 ? overrides.join(', ') : 'none'}`;
    }
    if (ACTIONS_WITH_REASON.has(event.action)) return reasonText(event.detail['reason']);
    return null;
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
