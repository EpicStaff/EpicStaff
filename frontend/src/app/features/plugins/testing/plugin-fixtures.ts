import { AvailablePlugin } from '../models/available-plugin.model';
import { PackageReview, PluginDetail } from '../models/plugin-admin.model';

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
