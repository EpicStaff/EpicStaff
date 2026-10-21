import { PluginOutboundHost, PluginUserRef } from './plugin-admin.model';

/** The setting types a manifest may declare. */
export type PluginSettingType = 'string' | 'text' | 'integer' | 'boolean' | 'url' | 'enum' | 'secret';

export type PluginSettingScalar = string | number | boolean;

/** One setting of a plugin with a backend, as the SuperAdmin sees it. Settings are deployment-wide. */
export interface PluginSettingState {
    key: string;
    type: PluginSettingType;
    label: string;
    description: string;
    required: boolean;
    /** The options of an `enum`, else `null`. */
    values: string[] | null;
    /** Never set for a `secret`. */
    default: PluginSettingScalar | null;
    /** The stored value; always `null` for a `secret`. */
    value: PluginSettingScalar | null;
    /** A value is stored (of any type). */
    is_set: boolean;
    /** The last 4 characters of a stored secret, else `null`. */
    tail: string | null;
    updated_at: string | null;
    updated_by: PluginUserRef | null;
}

/** `GET` and `PATCH /api/admin/plugins/{identifier}/settings/`. */
export interface PluginSettingsResponse {
    /** In manifest order. */
    settings: PluginSettingState[];
    /** Keys of required settings with neither a value nor a default: the plugin stays stopped until they are set. */
    missing_required: string[];
}

/** Only the keys to change; `null` clears a stored value. */
export interface PluginSettingsUpdate {
    values: Record<string, PluginSettingScalar | null>;
}

export type PluginCpuPriority = 'normal' | 'low';

export interface PluginLimitValues {
    memory_mb: number;
    db_connections: number;
    statement_timeout_seconds: number;
    requests_per_minute: number;
    cpu_priority: PluginCpuPriority;
}

export type PluginLimitKey = keyof PluginLimitValues;

export type PluginNumericLimitKey = Exclude<PluginLimitKey, 'cpu_priority'>;

/** `GET` and `PATCH /api/admin/plugins/{identifier}/limits/`. */
export interface PluginLimitsResponse {
    /** The manifest's values; platform defaults where the manifest has none. */
    requested: PluginLimitValues;
    platform_max: Record<PluginNumericLimitKey, number>;
    /** What the SuperAdmin lowered. */
    overrides: Partial<PluginLimitValues>;
    /** `min(requested, platform_max, override)`; CPU priority `low` when either side says so. */
    effective: PluginLimitValues;
    /** Whether each limit applies to this plugin; the database limits only when it has a database. */
    enforced: Record<PluginLimitKey, boolean>;
    /** The current package has a database. */
    has_database: boolean;
}

/** Only the overrides to change; `null` removes one. */
export interface PluginLimitsUpdate {
    overrides: Partial<Record<PluginLimitKey, number | 'low' | null>>;
}

export type PluginDesiredState = 'running' | 'stopped';

export type PluginObservedState =
    | 'unknown'
    | 'downloading'
    | 'building'
    | 'starting'
    | 'running'
    | 'stopped'
    | 'failed';

export type PluginHealth = 'ok' | 'failing' | 'unknown';

export type PluginBlockedReason = 'required_settings_missing';

export interface PluginRuntimeNode {
    name: string;
    /** The node reported within the last 30 seconds. */
    online: boolean;
    last_seen_at: string | null;
    agent_version: string | null;
}

export interface PluginPlacement {
    port: number;
    unix_uid: number;
    desired_state: PluginDesiredState;
    blocked_reason: PluginBlockedReason | null;
    observed_state: PluginObservedState;
    observed_version: string | null;
    health: PluginHealth;
    pid: number | null;
    restarts: number;
    rss_mb: number | null;
    last_error: string | null;
    /** At most 200 lines, filled when the process failed. */
    log_tail: string[];
    last_report_at: string | null;
}

/** `pending` until the node first tries to set it up. */
export type PluginDatabaseState = 'pending' | 'provisioning' | 'ready' | 'failed';

/** The plugin's own database on the deployment's plugin database server. No password ever reaches the browser. */
export interface PluginRuntimeDatabase {
    state: PluginDatabaseState;
    server: { name: string; host: string; port: number };
    database_name: string;
    roles: { owner: string; app: string; job: string };
    /** `applied` in the order they ran; `in_package`: how many the current package has. */
    migrations: { applied: string[]; in_package: number };
    /** Effective. */
    connection_limit: number;
    /** Effective. */
    statement_timeout_seconds: number;
    size_bytes: number | null;
    last_error: string | null;
    ready_at: string | null;
    /** When the platform last set the timeout back after the plugin changed its own default. */
    limits_restored_at: string | null;
}

/** The hosts the backend may reach through the egress proxy. */
export interface PluginRuntimeEgress {
    /** In manifest order; `[]`: the backend cannot reach the internet. */
    hosts: PluginOutboundHost[];
}

/** `GET .../runtime/` and `POST .../restart/` (202). */
export interface PluginRuntimeResponse {
    node: PluginRuntimeNode | null;
    /** `null` before the first approval of a package with a backend. */
    placement: PluginPlacement | null;
    /** `null`: the current package has no database. */
    database: PluginRuntimeDatabase | null;
    /** `null`: the plugin has no backend. */
    egress: PluginRuntimeEgress | null;
}
