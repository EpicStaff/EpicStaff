import { AvailablePlugin, AvailablePluginNavigationItem } from '../models/available-plugin.model';
import { OrganizationServiceAccount, PluginActivityEvent } from '../models/plugin-activity.model';
import {
    PackageReview,
    PluginAccessGrowth,
    PluginBackup,
    PluginBackupList,
    PluginDetail,
    PluginGrant,
    PluginOrgRemovedJob,
    PluginPurgeProgress,
    PluginRestore,
    PluginReviewNavigationItem,
    PluginSettingNeeded,
    PluginSummary,
    PluginUpgrade,
    PluginUpgradeHook,
    PluginUpgradeReview,
} from '../models/plugin-admin.model';
import {
    PluginLimitsResponse,
    PluginPlacement,
    PluginRuntimeDatabase,
    PluginRuntimeResponse,
    PluginSettingsResponse,
    PluginSettingState,
} from '../models/plugin-backend.model';
import { PluginDevelopment, PluginDevelopmentTarget } from '../models/plugin-development.model';
import { PluginGrantPurgePreview, PluginPurgePreview } from '../models/plugin-purge-preview.model';
import { PluginRolePermissionsResponse, PluginRoleRow } from '../models/plugin-role-permissions.model';
import { PluginSuspendPreview } from '../models/plugin-suspend-preview.model';

/** A pending review of the Weather sample (frontend only), signed by a trusted key. */
export function buildPackageReview(overrides: Partial<PackageReview> = {}): PackageReview {
    return {
        id: 11,
        plugin_identifier: 'weather',
        version: '0.1.0',
        name: 'Weather',
        description: 'Forecasts for the places your organization cares about.',
        publisher: { name: 'EpicStaff', url: null },
        icon_data_url: 'data:image/svg+xml;base64,PHN2Zy8+',
        navigation: [],
        trust: 'trusted',
        signature: 'valid',
        signer: { key_name: 'release', key_id: '0123456789abcdef' },
        review_state: 'pending',
        sha256: 'a'.repeat(64),
        size: 2048,
        uploaded_at: '2026-10-20T10:00:00Z',
        uploaded_by: { id: 1, email: 'admin@example.com' },
        approved_at: null,
        approved_by: null,
        is_upgrade: false,
        current_version: null,
        contents: {
            has_spa: true,
            has_backend: false,
            has_database: false,
            spa_file_count: 3,
            spa_bytes: 4096,
            wheel_count: 0,
            migration_count: 0,
        },
        access: [],
        user_permissions: [
            {
                action: 'read',
                label: 'View',
                description: 'Open Weather and see forecasts.',
                defaults: { org_admin: true, member: true, viewer: false },
            },
        ],
        public_paths: [],
        outbound_hosts: [],
        settings: [],
        limits: null,
        hooks: { install: false, upgrade: false, org_removed: false },
        warnings: [],
        access_growth: null,
        upgrade: null,
        ...overrides,
    };
}

/** The Overview entry of a package's app menu, its icon inlined for the review; it needs no permission. */
export function buildReviewNavigationItem(
    overrides: Partial<PluginReviewNavigationItem> = {}
): PluginReviewNavigationItem {
    return {
        label: 'Overview',
        path: '/',
        icon_data_url: 'data:image/svg+xml;base64,PHN2Zy8+',
        permission: null,
        ...overrides,
    };
}

/** Weather running, as the plugin list shows it. */
export function buildPluginSummary(overrides: Partial<PluginSummary> = {}): PluginSummary {
    return {
        identifier: 'weather',
        name: 'Weather',
        description: 'Forecasts for the places your organization cares about.',
        state: 'running',
        trust: 'trusted',
        current_version: '0.1.0',
        icon_url: '/api/plugin-public/weather/icon/?v=0.1.0',
        frame_origin: 'https://weather.plugins.example.com',
        grant_count: 0,
        pending_package: null,
        created_at: '2026-10-20T10:00:00Z',
        purge_after: null,
        needs_attention: false,
        upgrade: null,
        development: null,
        ...overrides,
    };
}

export function buildPluginDetail(overrides: Partial<PluginDetail> = {}): PluginDetail {
    return {
        ...buildPluginSummary(),
        current_package: buildPackageReview({ review_state: 'approved', current_version: '0.1.0' }),
        allowed_actions: ['uninstall', 'purge'],
        uninstall_requested_at: null,
        purge_started_at: null,
        purge_progress: null,
        open_upgrade: null,
        last_upgrade: null,
        upgrade_hooks: { upgrading: 0, upgrade_failed: 0 },
        development_mode: false,
        ...overrides,
    };
}

/** Weather being deleted: one organization left, its data removal waiting, the node waiting for it. */
export function buildPluginPurgeProgress(overrides: Partial<PluginPurgeProgress> = {}): PluginPurgeProgress {
    return {
        grants_left: 1,
        data_removals_waiting: 1,
        data_removals_failed: 0,
        node: 'waiting',
        node_error: null,
        ...overrides,
    };
}

/** Weather as a member sees it: one page, no app menu. */
export function buildAvailablePlugin(overrides: Partial<AvailablePlugin> = {}): AvailablePlugin {
    return {
        identifier: 'weather',
        name: 'Weather',
        description: 'Forecasts for the places your organization cares about.',
        icon_url: '/api/plugin-public/weather/icon/?v=0.1.0',
        frame_origin: 'https://weather.plugins.example.com',
        permissions: ['read'],
        availability: 'ready',
        development: false,
        navigation: [],
        ...overrides,
    };
}

/** The Overview entry of Weather's app menu, its icon served from version 0.1.0. */
export function buildAvailablePluginNavigationItem(
    overrides: Partial<AvailablePluginNavigationItem> = {}
): AvailablePluginNavigationItem {
    return {
        label: 'Overview',
        path: '/',
        icon_url: '/api/plugin-public/weather/icons/overview.svg/?v=0.1.0',
        ...overrides,
    };
}

/** Weather's backend on port 8001 of the author's machine, and its page from the development server on 5173. */
export function buildPluginDevelopmentTarget(
    overrides: Partial<PluginDevelopmentTarget> = {}
): PluginDevelopmentTarget {
    return {
        backend_port: 8001,
        spa_port: 5173,
        updated_at: '2026-10-22T09:00:00Z',
        updated_by: { id: 1, email: 'sam@example.com' },
        ...overrides,
    };
}

/** Development mode on, the host resolving as on Docker Desktop, Weather with a backend and a page, nothing stored. */
export function buildPluginDevelopment(overrides: Partial<PluginDevelopment> = {}): PluginDevelopment {
    return {
        development_mode: true,
        host: 'host.docker.internal',
        host_address: '192.168.65.254',
        api_url: 'http://127.0.0.1:8082/api/',
        can_use_backend: true,
        can_use_spa: true,
        target: null,
        runtime_file_issued_at: null,
        ...overrides,
    };
}

/** The Weather row of the Roles matrix as `rows/` sends it: View and Edit declared, the caller may grant View only. */
export function buildPluginRoleRow(overrides: Partial<PluginRoleRow> = {}): PluginRoleRow {
    return {
        plugin_identifier: 'weather',
        name: 'Weather',
        icon_url: '/api/plugin-public/weather/icon/?v=0.2.0',
        actions: [
            { action: 'read', label: 'View', description: 'Open Weather and see forecasts.' },
            { action: 'update', label: 'Edit', description: 'Change the places Weather forecasts.' },
        ],
        ceiling: ['read'],
        ...overrides,
    };
}

/** A custom role of org 1 holding View on Weather, editable by the caller. */
export function buildPluginRolePermissions(
    overrides: Partial<PluginRolePermissionsResponse> = {}
): PluginRolePermissionsResponse {
    return {
        role: { id: 7, name: 'Forecasters', is_built_in: false, org_id: 1 },
        organization: { id: 1, name: 'Org A' },
        editable: true,
        rows: [{ ...buildPluginRoleRow(), granted: ['read'] }],
        ...overrides,
    };
}

export function buildPluginSetting(overrides: Partial<PluginSettingState> = {}): PluginSettingState {
    return {
        key: 'units',
        type: 'enum',
        label: 'Units',
        description: 'How forecasts show temperatures.',
        required: false,
        values: ['metric', 'imperial'],
        default: 'metric',
        value: null,
        is_set: false,
        tail: null,
        updated_at: null,
        updated_by: null,
        ...overrides,
    };
}

/** Weather 0.2.0's settings, nothing stored yet. */
export function buildPluginSettings(overrides: Partial<PluginSettingsResponse> = {}): PluginSettingsResponse {
    return {
        settings: [
            buildPluginSetting(),
            buildPluginSetting({
                key: 'forecast_api_token',
                type: 'secret',
                label: 'Forecast API token',
                description: 'The token of the forecast service.',
                values: null,
                default: null,
            }),
        ],
        missing_required: [],
        ...overrides,
    };
}

/** The manifest asks for 256 MB; nothing is overridden; no database, so only the database limits do not apply. */
export function buildPluginLimits(overrides: Partial<PluginLimitsResponse> = {}): PluginLimitsResponse {
    return {
        requested: {
            memory_mb: 256,
            db_connections: 5,
            statement_timeout_seconds: 30,
            requests_per_minute: 120,
            cpu_priority: 'normal',
        },
        platform_max: { memory_mb: 1024, db_connections: 20, statement_timeout_seconds: 60, requests_per_minute: 600 },
        overrides: {},
        effective: {
            memory_mb: 256,
            db_connections: 5,
            statement_timeout_seconds: 30,
            requests_per_minute: 120,
            cpu_priority: 'normal',
        },
        enforced: {
            memory_mb: true,
            db_connections: false,
            statement_timeout_seconds: false,
            requests_per_minute: true,
            cpu_priority: true,
        },
        has_database: false,
        ...overrides,
    };
}

export function buildPluginPlacement(overrides: Partial<PluginPlacement> = {}): PluginPlacement {
    return {
        port: 20001,
        unix_uid: 20001,
        desired_state: 'running',
        blocked_reason: null,
        observed_state: 'running',
        observed_version: '0.2.0',
        health: 'ok',
        pid: 412,
        restarts: 0,
        rss_mb: 61.4,
        last_error: null,
        log_tail: [],
        last_report_at: '2026-10-21T08:00:05Z',
        ...overrides,
    };
}

/** Weather running healthy on an online node, with no database and no outbound host. */
export function buildPluginRuntime(overrides: Partial<PluginRuntimeResponse> = {}): PluginRuntimeResponse {
    return {
        node: { name: 'node-1', online: true, last_seen_at: '2026-10-21T08:00:05Z', agent_version: '0.1.0' },
        placement: buildPluginPlacement(),
        database: null,
        egress: { hosts: [] },
        upgrade: null,
        ...overrides,
    };
}

/** Weather 0.5.0's database, ready: its one migration applied, 3 connections, a 10 s statement timeout. */
export function buildPluginRuntimeDatabase(overrides: Partial<PluginRuntimeDatabase> = {}): PluginRuntimeDatabase {
    return {
        state: 'ready',
        server: { name: 'plugins_db', host: 'plugins_db', port: 5432 },
        database_name: 'plugin_weather',
        roles: { owner: 'weather_owner', app: 'weather_app', job: 'weather_job' },
        migrations: { applied: ['001_weather.sql'], in_package: 1 },
        connection_limit: 3,
        statement_timeout_seconds: 10,
        size_bytes: 7_654_321,
        last_error: null,
        ready_at: '2026-10-21T08:00:30Z',
        limits_restored_at: null,
        ...overrides,
    };
}

/** Weather granted to Acme by a SuperAdmin; its backend acts there, its install hook succeeded, it owns 2 resources. */
export function buildPluginGrant(overrides: Partial<PluginGrant> = {}): PluginGrant {
    return {
        id: 5,
        plugin_identifier: 'weather',
        organization: { id: 3, name: 'Acme' },
        state: 'active',
        allowed_actions: ['suspend', 'purge'],
        granted_by: { id: 1, email: 'sam@example.com' },
        granted_at: '2026-10-21T08:00:00Z',
        suspended_at: null,
        purge_after: null,
        last_hook_error: null,
        service_account: { created_at: '2026-10-21T08:00:00Z', key_last_used_at: null },
        install_hook: {
            state: 'succeeded',
            attempt: 1,
            started_at: '2026-10-21T08:00:05Z',
            finished_at: '2026-10-21T08:00:09Z',
            error: null,
        },
        owned_resource_count: 2,
        suspension_cause: null,
        purge_started_at: null,
        last_purge_error: null,
        org_removed_hook: null,
        installed_version: '0.1.0',
        upgrade_hook: null,
        ...overrides,
    };
}

/** Weather deleting its own data for Acme: the first attempt failed, the next one is due in a minute. */
export function buildOrgRemovedJob(overrides: Partial<PluginOrgRemovedJob> = {}): PluginOrgRemovedJob {
    return {
        id: 31,
        organization: { id: 3, name: 'Acme', exists: true },
        grant_id: 5,
        state: 'pending',
        attempt: 1,
        first_attempt_at: '2026-10-21T09:00:00Z',
        next_attempt_at: '2026-10-21T09:01:00Z',
        retry_until: '2026-10-28T09:00:00Z',
        finished_at: null,
        error: 'Weather answered HTTP 500.',
        created_at: '2026-10-21T08:59:50Z',
        allowed_actions: ['retry', 'skip'],
        ...overrides,
    };
}

/**
 * What deleting Weather's data in Acme removes: Weather owns a flow, a file, a secret and an LLM config there, "Daily
 * digest" uses the LLM config, "Weather forecast" is Weather's own flow, the agent default model points at Weather's
 * config, and Weather deletes its own data for Acme through its hook.
 */
export function buildGrantPurgePreview(overrides: Partial<PluginGrantPurgePreview> = {}): PluginGrantPurgePreview {
    return {
        grant: { id: 5, state: 'active' },
        plugin: { identifier: 'weather', name: 'Weather' },
        organization: { id: 3, name: 'Acme' },
        verification_phrase: 'purge-weather-Acme',
        owned_resources: [
            { model: 'tables.StorageFile', label: 'Files', count: 1 },
            { model: 'tables.Graph', label: 'Flows', count: 1 },
            { model: 'tables.LLMConfig', label: 'LLM configs', count: 1 },
            { model: 'tables.Secret', label: 'Secrets', count: 1 },
        ],
        flows: {
            organization: { total: 1, items: [{ id: 21, name: 'Daily digest' }] },
            plugin: { total: 1, items: [{ id: 18, name: 'Weather forecast' }] },
        },
        running_sessions: {
            total: 1,
            items: [
                {
                    id: 301,
                    flow: { id: 21, name: 'Daily digest' },
                    status: 'run',
                    created_at: '2026-10-21T08:00:00Z',
                },
            ],
        },
        default_models: [{ setting: 'agent_llm_config', config: { id: 9, name: 'Weather summaries' } }],
        plugin_data: 'deleted_by_plugin',
        ...overrides,
    };
}

/**
 * What uninstalling or deleting Weather affects: it is granted to Acme only, owns a flow and a file there, has an
 * organization removed hook, a database of 7.3 MB, a backend and a frontend.
 */
export function buildPluginPurgePreview(overrides: Partial<PluginPurgePreview> = {}): PluginPurgePreview {
    return {
        plugin: { identifier: 'weather', name: 'Weather', state: 'running' },
        verification_phrase: 'purge-weather',
        data_kept_until: '2026-11-20T09:00:00Z',
        organizations: {
            total: 1,
            items: [{ grant_id: 5, organization: { id: 3, name: 'Acme' }, state: 'active', owned_resource_count: 2 }],
        },
        owned_resources: [
            { model: 'tables.StorageFile', label: 'Files', count: 1 },
            { model: 'tables.Graph', label: 'Flows', count: 1 },
        ],
        data_removals_open: 0,
        has_org_removed_hook: true,
        database: { name: 'plugin_weather', size_bytes: 7_654_321 },
        has_backend: true,
        has_spa: true,
        package_count: 1,
        ...overrides,
    };
}

/**
 * What suspending Weather in Acme stops: "Daily digest" uses Weather's LLM config and is running on a schedule,
 * "Weather forecast" is Weather's own flow, and the agent default model points at Weather's config.
 */
export function buildSuspendPreview(overrides: Partial<PluginSuspendPreview> = {}): PluginSuspendPreview {
    return {
        grant: { id: 5, state: 'active' },
        plugin: { identifier: 'weather', name: 'Weather' },
        organization: { id: 3, name: 'Acme' },
        data_kept_until: '2026-11-20T08:00:00Z',
        owned_resources: [
            { model: 'tables.StorageFile', label: 'Files', count: 1 },
            { model: 'tables.Graph', label: 'Flows', count: 1 },
            { model: 'tables.LLMConfig', label: 'LLM configs', count: 1 },
            { model: 'tables.Secret', label: 'Secrets', count: 1 },
        ],
        flows: {
            organization: { total: 1, items: [{ id: 21, name: 'Daily digest' }] },
            plugin: { total: 1, items: [{ id: 18, name: 'Weather forecast' }] },
        },
        running_sessions: {
            total: 1,
            items: [
                {
                    id: 301,
                    flow: { id: 21, name: 'Daily digest' },
                    status: 'run',
                    created_at: '2026-10-21T08:00:00Z',
                },
            ],
        },
        triggers: {
            total: 1,
            items: [
                { kind: 'schedule', node_id: 44, node_name: 'Every 2 minutes', flow: { id: 21, name: 'Daily digest' } },
            ],
        },
        realtime_agents: { total: 0, items: [] },
        voice_channels: { total: 0, items: [] },
        default_models: [{ setting: 'agent_llm_config', config: { id: 9, name: 'Weather summaries' } }],
        ...overrides,
    };
}

/** Weather running its flow in Acme on behalf of Ada. */
export function buildPluginActivityEvent(overrides: Partial<PluginActivityEvent> = {}): PluginActivityEvent {
    return {
        id: 41,
        created_at: '2026-10-21T08:10:00Z',
        plugin: { identifier: 'weather', name: 'Weather' },
        organization: { id: 3, name: 'Acme' },
        actor: { kind: 'plugin', label: 'Weather (plugin)' },
        on_behalf_of: { user_id: 12, label: 'ada@example.com' },
        action: 'api_request',
        request: { method: 'POST', path: '/api/run-session/', route: 'api/run-session/', status: 201 },
        target: { resource_type: 'flows', id: '18', label: 'Weather forecast' },
        detail: { created_count: 1 },
        ...overrides,
    };
}

/** Weather acting in the active organization, with the flows and files access it declares, no host and no database. */
export function buildOrganizationServiceAccount(
    overrides: Partial<OrganizationServiceAccount> = {}
): OrganizationServiceAccount {
    return {
        plugin: { identifier: 'weather', name: 'Weather', icon_url: '/api/plugin-public/weather/icon/?v=0.4.0' },
        grant_state: 'active',
        created_at: '2026-10-21T08:00:00Z',
        key_last_used_at: null,
        access: [
            {
                resource_type: 'flows',
                resource_label: 'Flows',
                actions: ['read', 'create', 'update', 'use'],
                reason: 'Creates the Weather forecast flow and runs it for you.',
            },
            {
                resource_type: 'files',
                resource_label: 'Files',
                actions: ['read', 'create'],
                reason: "Stores the Weather readme in your organization's storage.",
            },
        ],
        outbound_hosts: [],
        has_database: false,
        ...overrides,
    };
}

/** Weather's upgrade from 0.6.0 to 0.7.0 as Sam started it: the node prepares 0.7.0 while 0.6.0 keeps running. */
export function buildPluginUpgrade(overrides: Partial<PluginUpgrade> = {}): PluginUpgrade {
    return {
        id: 7,
        from_version: '0.6.0',
        to_version: '0.7.0',
        stage: 'preparing',
        step: 'download',
        failed: false,
        failed_at: null,
        last_error: null,
        adds_backend: false,
        database_changed: false,
        backup_id: null,
        restore: null,
        started_by: { id: 1, email: 'sam@example.com' },
        started_at: '2026-10-21T10:00:00Z',
        maintenance_started_at: null,
        migrations_started_at: null,
        finished_at: null,
        ...overrides,
    };
}

/** The same upgrade offline: the plugin is in maintenance, the backup taken, the migrations running. */
export function buildMigratingUpgrade(overrides: Partial<PluginUpgrade> = {}): PluginUpgrade {
    return buildPluginUpgrade({
        stage: 'migrating',
        step: 'migrate',
        backup_id: 61,
        maintenance_started_at: '2026-10-21T10:01:00Z',
        migrations_started_at: '2026-10-21T10:01:40Z',
        ...overrides,
    });
}

/** Weather's upgrade to 0.7.1 that failed on its broken migration after applying the one before it. */
export function buildFailedMigrationUpgrade(overrides: Partial<PluginUpgrade> = {}): PluginUpgrade {
    return buildMigratingUpgrade({
        id: 8,
        from_version: '0.7.0',
        to_version: '0.7.1',
        failed: true,
        failed_at: '2026-10-21T11:02:00Z',
        last_error: '005_broken.sql line 1: [22012] division by zero',
        database_changed: true,
        backup_id: 62,
        ...overrides,
    });
}

/** Sam restoring the backup taken before the upgrade to 0.7.1: the node is restoring it. */
export function buildPluginRestore(overrides: Partial<PluginRestore> = {}): PluginRestore {
    return {
        id: 4,
        backup: { id: 62, file_name: '20261021T110100Z-u8-pre_upgrade.dump', reason: 'pre_upgrade' },
        state: 'running',
        step: 'restore',
        pre_restore_backup_id: null,
        last_error: null,
        requested_by: { id: 1, email: 'sam@example.com' },
        requested_at: '2026-10-21T11:05:00Z',
        finished_at: null,
        ...overrides,
    };
}

/** The backup taken before the upgrade to 0.7.0, holding 0.6.0's database: restorable while that upgrade is open. */
export function buildPluginBackup(overrides: Partial<PluginBackup> = {}): PluginBackup {
    return {
        id: 61,
        file_name: '20261021T100130Z-u7-pre_upgrade.dump',
        reason: 'pre_upgrade',
        version: '0.6.0',
        upgrade: { id: 7, to_version: '0.7.0' },
        size_bytes: 7_654_321,
        created_at: '2026-10-21T10:01:30Z',
        restorable: false,
        not_restorable_reason: 'not_now',
        ...overrides,
    };
}

export function buildPluginBackupList(overrides: Partial<PluginBackupList> = {}): PluginBackupList {
    return {
        verification_phrase: 'restore-weather',
        backups: [buildPluginBackup()],
        ...overrides,
    };
}

/** What Weather 0.7.0 adds: it reaches Open-Meteo for current temperatures. */
export function buildAccessGrowth(overrides: Partial<PluginAccessGrowth> = {}): PluginAccessGrowth {
    return {
        requires_acknowledgement: true,
        access: [],
        outbound_hosts: [{ host: 'api.open-meteo.com', reason: 'Looks up the current temperature of saved places.' }],
        public_paths: [],
        ...overrides,
    };
}

export function buildSettingNeeded(overrides: Partial<PluginSettingNeeded> = {}): PluginSettingNeeded {
    return {
        key: 'units',
        type: 'enum',
        label: 'Units',
        description: 'How temperatures are shown.',
        reason: 'required',
        values: ['metric', 'imperial'],
        ...overrides,
    };
}

/**
 * Upgrading Weather from 0.6.0 to 0.7.0: one new migration, an upgrade hook, a database of 7.3 MB backed up first,
 * Acme and Beta offline until their upgrade finishes, and Cancel possible.
 */
export function buildUpgradeReview(overrides: Partial<PluginUpgradeReview> = {}): PluginUpgradeReview {
    return {
        baseline_package_id: 10,
        from_version: '0.6.0',
        replaces_version: null,
        trust_change: 'none',
        maintenance: true,
        backend: 'unchanged',
        database: 'unchanged',
        migrations_added: ['003_place_conditions.sql'],
        hooks_added: ['upgrade'],
        hooks_removed: [],
        has_upgrade_hook: true,
        user_permissions: { added: [], removed: [], defaults_changed: [] },
        settings: { added: [], removed: [], needed: [] },
        limits_changed: [],
        navigation_changed: false,
        backup: { required: true, database_name: 'plugin_weather', database_size_bytes: 7_654_321 },
        organizations_going_offline: 2,
        cancellable: true,
        ...overrides,
    };
}

/** The pending review of Weather 0.7.0 for an installed 0.6.0, with its new outbound host to approve. */
export function buildUpgradePackageReview(overrides: Partial<PackageReview> = {}): PackageReview {
    const review = buildPackageReview();
    return buildPackageReview({
        id: 12,
        version: '0.7.0',
        is_upgrade: true,
        current_version: '0.6.0',
        contents: { ...review.contents, has_backend: true, has_database: true, wheel_count: 4, migration_count: 3 },
        hooks: { install: true, upgrade: true, org_removed: true },
        access_growth: buildAccessGrowth(),
        upgrade: buildUpgradeReview(),
        ...overrides,
    });
}

/** Acme's upgrade hook from 0.6.0: the first attempt failed, the next one is due at 10:05. */
export function buildUpgradeHook(overrides: Partial<PluginUpgradeHook> = {}): PluginUpgradeHook {
    return {
        state: 'pending',
        attempt: 1,
        from_version: '0.6.0',
        next_attempt_at: '2026-10-21T10:05:00Z',
        started_at: '2026-10-21T10:03:50Z',
        finished_at: null,
        error: 'Weather answered HTTP 500.',
        ...overrides,
    };
}
