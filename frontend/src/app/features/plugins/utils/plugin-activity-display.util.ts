import { PluginActivityAction, PluginActivityEvent } from '../models/plugin-activity.model';

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
};

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

/** The organization's name, or that the event concerns the whole deployment. */
export function pluginActivityOrganizationText(event: PluginActivityEvent): string {
    const organization = event.organization;
    if (!organization) return 'Whole deployment';
    return organization.name ?? `Organization ${organization.id}`;
}

export function pluginActivityPluginText(event: PluginActivityEvent): string {
    return event.plugin.name ?? event.plugin.identifier;
}

/** The hook's own error message of a failed install, else `null`. */
export function pluginActivityErrorText(event: PluginActivityEvent): string | null {
    if (event.action !== 'install_hook_failed') return null;
    const error = event.detail['error'];
    return typeof error === 'string' && error ? error : null;
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
