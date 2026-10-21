import { PluginDeclaredAccess, PluginGrantState, PluginOutboundHost } from './plugin-admin.model';

/** What a plugin did, or what was done to it. */
export type PluginActivityAction =
    | 'api_request'
    | 'package_approved'
    | 'grant_created'
    | 'install_hook_succeeded'
    | 'install_hook_failed'
    | 'install_hook_retried'
    | 'settings_changed'
    | 'limits_changed'
    | 'restarted'
    | 'grant_suspended'
    | 'grant_resumed'
    | 'database_ready'
    | 'database_failed'
    | 'database_limit_restored'
    | 'plugin_uninstalled'
    | 'plugin_reinstalled'
    | 'plugin_purge_started'
    | 'plugin_removal_failed'
    | 'plugin_removal_retried'
    | 'plugin_purged'
    | 'grant_purge_started'
    | 'grant_purged'
    | 'org_removed_hook_succeeded'
    | 'org_removed_hook_failed'
    | 'org_removed_hook_retried'
    | 'org_removed_hook_skipped';

/** Why a deletion began (`detail.reason` of `grant_purge_started` and `plugin_purge_started`). */
export type PluginPurgeReason = 'requested' | 'grace_period_over' | 'plugin_deleted';

/** `plugin`: its service account; `superadmin`: a SuperAdmin on the admin pages; `platform`: EpicStaff itself. */
export type PluginActivityActorKind = 'plugin' | 'superadmin' | 'platform';

export type PluginActivityDetailValue = string | number | boolean | null | string[];

export interface PluginActivityEvent {
    id: number;
    created_at: string;
    /** `name` is `null` once the plugin is gone. */
    plugin: { identifier: string; name: string | null };
    /** `null` for an event of the whole deployment; `name` is `null` once the organization is gone. */
    organization: { id: number; name: string | null } | null;
    /** `label`: the plugin's "<name> (plugin)", or the SuperAdmin's email when the event happened. */
    actor: { kind: PluginActivityActorKind; label: string };
    /** The person a plugin acted for; `label` is their email when the event happened. */
    on_behalf_of: { user_id: number | null; label: string } | null;
    action: PluginActivityAction;
    /** Only for `api_request`; `path` carries no query string; `route` is the URL pattern, like `api/graphs/<pk>/`. */
    request: { method: string; path: string; route: string | null; status: number } | null;
    target: { resource_type: string | null; id: string | null; label: string | null } | null;
    /**
     * Never holds a secret. `limits_changed`: the overrides in force after the change, one per limit (`{}` when none
     * is left); `install_hook_failed`, `database_failed`, `plugin_removal_failed` and `org_removed_hook_failed`:
     * `error`; `grant_purge_started` and `plugin_purge_started`: `reason`.
     */
    detail: Record<string, PluginActivityDetailValue>;
}

/** A plugin with a backend acting in the active organization, and what it declared it may do there. */
export interface OrganizationServiceAccount {
    plugin: { identifier: string; name: string; icon_url: string };
    grant_state: PluginGrantState;
    created_at: string;
    key_last_used_at: string | null;
    /** As the package review shows it. */
    access: PluginDeclaredAccess[];
    /** The hosts its backend may reach on the internet, in manifest order. */
    outbound_hosts: PluginOutboundHost[];
    /** It keeps its data in a database of its own. */
    has_database: boolean;
}

/** The filters of the active organization's activity list. */
export interface PluginActivityQuery {
    page: number;
    pageSize: number;
    /** A plugin identifier. */
    plugin?: string | null;
    action?: PluginActivityAction | null;
}

/** The filters of one plugin's activity list on the admin pages (every organization and the deployment). */
export interface PluginAdminActivityQuery {
    page: number;
    pageSize: number;
    organizationId?: number | null;
    action?: PluginActivityAction | null;
}
