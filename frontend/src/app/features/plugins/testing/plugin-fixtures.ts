import { AvailablePlugin } from '../models/available-plugin.model';
import { PackageReview, PluginDetail } from '../models/plugin-admin.model';
import {
    PluginLimitsResponse,
    PluginPlacement,
    PluginRuntimeResponse,
    PluginSettingsResponse,
    PluginSettingState,
} from '../models/plugin-backend.model';
import { PluginRolePermissionsResponse, PluginRoleRow } from '../models/plugin-role-permissions.model';

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
        ...overrides,
    };
}

export function buildPluginDetail(overrides: Partial<PluginDetail> = {}): PluginDetail {
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
        current_package: buildPackageReview({ review_state: 'approved' }),
        ...overrides,
    };
}

export function buildAvailablePlugin(overrides: Partial<AvailablePlugin> = {}): AvailablePlugin {
    return {
        identifier: 'weather',
        name: 'Weather',
        icon_url: '/api/plugin-public/weather/icon/?v=0.1.0',
        frame_origin: 'https://weather.plugins.example.com',
        permissions: ['read'],
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

/** The manifest asks for 256 MB; nothing is overridden; only memory and CPU are enforced. */
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
            requests_per_minute: false,
            cpu_priority: true,
        },
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

/** Weather running healthy on an online node. */
export function buildPluginRuntime(overrides: Partial<PluginRuntimeResponse> = {}): PluginRuntimeResponse {
    return {
        node: { name: 'node-1', online: true, last_seen_at: '2026-10-21T08:00:05Z', agent_version: '0.1.0' },
        placement: buildPluginPlacement(),
        ...overrides,
    };
}
