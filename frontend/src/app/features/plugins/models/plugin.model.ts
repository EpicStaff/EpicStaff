import { ReviewItem } from '../../../core/models/review-item.model';

/** What drives the UI: `suspended` when suspended, otherwise the plugin's `state`. */
export type PluginStatus = 'preparing' | 'ready' | 'needs_attention' | 'suspended';

/** Lifecycle state, independent of suspension. */
export type PluginState = Exclude<PluginStatus, 'suspended'>;

/** Keys used by `contents`, `resources[].type` and the delete preview. */
export type PluginResourceType =
    | 'flow'
    | 'agent_definition'
    | 'surface'
    | 'llm_config'
    | 'embedding_config'
    | 'python_code_tool'
    | 'mcp_tool'
    | 'webhook_trigger'
    | 'secret'
    | 'source_collection'
    | 'storage_file'
    | 'key_value_table'
    | 'llm_model'
    | 'embedding_model';

/** `run`, `sessions.read`, `sessions.stop` apply to a flow; `read` to a key-value table. */
export type PluginAccessAction = 'run' | 'sessions.read' | 'sessions.stop' | 'read';

/** What an access entry may point at. A `key_value_table` entry needs bridge version 2. */
export type PluginAccessTargetType = 'flow' | 'key_value_table';

export type PluginContentCounts = Partial<Record<PluginResourceType, number>>;

export interface PluginAccessEntry {
    alias: string;
    type: PluginAccessTargetType;
    actions: PluginAccessAction[];
    /** `null` when the org deleted that flow or table. */
    resource_id: number | null;
    resource_name: string | null;
}

/** The plugin resources that can send a secret slot's value out of EpicStaff. */
export type PluginSecretDestinationType = 'llm_config' | 'embedding_config' | 'mcp_tool';

/** One place a slot's value is sent: the config or tool that uses it, and the endpoint it calls. */
export interface PluginSecretDestination {
    resource_type: PluginSecretDestinationType;
    name: string;
    provider: string | null;
    /** A custom endpoint host; `null` means the provider's standard endpoint. */
    host: string | null;
}

export interface PluginSecretSlot {
    name: string;
    description: string;
    /** Where the value is sent. Built by the same presenter for list and retrieve. */
    destinations: PluginSecretDestination[];
    /** `null` when the slot's secret was deleted (`configured: false`). */
    secret_id: number | null;
    secret_name: string | null;
    configured: boolean;
}

/** One item of `GET /api/plugins/` (no `resources`). */
export interface PluginSummary {
    id: number;
    plugin_id: string;
    version: string;
    name: string;
    description: string;
    /** `data:image/svg+xml;base64,...`, `data:image/png;base64,...` or `""`. Render only with `<img [src]>`. */
    icon_data_url: string;
    format_version: number;
    bridge_version: number;
    has_ui: boolean;
    status: PluginStatus;
    state: PluginState;
    /** Why the plugin needs attention; `""` otherwise. */
    status_reason: string;
    suspended: boolean;
    suspended_at: string | null;
    access: PluginAccessEntry[];
    secret_slots: PluginSecretSlot[];
    contents: PluginContentCounts;
    /** The instance runs with plugin dev mode on; only then can a dev URL be set or used. */
    dev_mode_available: boolean;
    /** Where the plugin's page loads from in dev mode, for `dev_ui_user` only; `null` when unset. */
    dev_ui_url: string | null;
    /** The user who set `dev_ui_url`; the only one who gets the dev page. */
    dev_ui_user: number | null;
    created_by: number | null;
    created_at: string;
    updated_at: string;
}

export interface PluginResource {
    type: PluginResourceType;
    resource_id: number;
    /** `null` when the org has since deleted the row (`exists: false`). */
    name: string | null;
    /** Where the row came from in the plugin file. */
    manifest_ref: string;
    exists: boolean;
}

/** Returned by retrieve, install, suspend, resume, retry and secrets. */
export interface PluginDetail extends PluginSummary {
    resources: PluginResource[];
}

/** `{id, plugin_id, name, version}`, used by the delete preview and the ui-session. */
export interface PluginReference {
    id: number;
    plugin_id: string;
    name: string;
    version: string;
}

// ---------------------------------------------------------------------------
// POST /api/plugins/inspect/
// ---------------------------------------------------------------------------

export interface PluginInspectManifest {
    plugin_id: string;
    version: string;
    name: string;
    description: string;
    icon_data_url: string;
    format_version: number;
    bridge_version: number;
    has_ui: boolean;
}

export interface PluginInspectContentItem {
    type: PluginResourceType;
    /** Where the item comes from in the plugin file. */
    ref: string;
    /**
     * For a secret: the org secret that will be created; for a storage file: the org storage path;
     * for a key-value table: the table name with the plugin prefix (`chat_admin__conversations`).
     */
    name: string;
    /** Only on `source_collection`. */
    documents?: string[];
}

export interface PluginInspectAccessEntry {
    alias: string;
    type: PluginAccessTargetType;
    /** The flow's or table's id inside the plugin file, not a database id. */
    ref: number;
    resource_name: string;
    actions: PluginAccessAction[];
}

export interface PluginInspectSecretSlot {
    name: string;
    description: string;
    /** The org secret the value will be stored as. */
    secret_name: string;
    /** Where the value will be sent. */
    destinations: PluginSecretDestination[];
}

/** An RBAC permission the installer lacks, e.g. `{resource_type: 'secrets', action: 'create'}`. */
export interface PluginMissingPermission {
    resource_type: string;
    action: string;
}

export interface PluginResourceConflict {
    type: 'secret' | 'storage_file' | 'key_value_table';
    name: string;
    message: string;
}

export interface PluginInspectResult {
    plugin: PluginInspectManifest;
    contents: PluginInspectContentItem[];
    content_counts: PluginContentCounts;
    access: PluginInspectAccessEntry[];
    secret_slots: PluginInspectSecretSlot[];
    /** Same item shape as `POST /api/graphs/import/inspect/` → `review_items`. */
    code_review_items: ReviewItem[];
    has_knowledge: boolean;
    ui_asset_count: number;
    /** Strings to show in the review step, in order. */
    warnings: string[];
    missing_permissions: PluginMissingPermission[];
    conflicts: PluginResourceConflict[];
    /** `missing_permissions` and `conflicts` are both empty. */
    can_install: boolean;
}

// ---------------------------------------------------------------------------
// POST /api/plugins/install/ and /api/plugins/{id}/secrets/
// ---------------------------------------------------------------------------

/** Slot name → value. */
export type PluginSecretValues = Record<string, string>;

/** Install progress: upload percentage while the file is sent, then the installed plugin. */
export type PluginInstallEvent = { kind: 'progress'; percent: number } | { kind: 'done'; plugin: PluginDetail };

export interface PluginSecretsRequest {
    secrets: PluginSecretValues;
    retry_indexing?: boolean;
}

// ---------------------------------------------------------------------------
// GET /api/plugins/{id}/delete-preview/
// ---------------------------------------------------------------------------

export interface PluginDeletePreviewResource {
    type: PluginResourceType;
    resource_id: number;
    name: string | null;
    /** Rows the org already deleted are listed with `exists: false` and skipped. */
    exists: boolean;
}

export interface PluginUsageReference {
    type: string;
    resource_id: number;
    name: string;
}

/** One of the org's own resources that references a plugin resource and will lose it. */
export interface PluginExternalUsage {
    type: PluginResourceType;
    resource_id: number;
    name: string;
    used_by: PluginUsageReference[];
}

export interface PluginDeletePreview {
    plugin: PluginReference;
    resources: PluginDeletePreviewResource[];
    resource_counts: PluginContentCounts;
    session_count: number;
    live_session_count: number;
    /** Friendly-name counts of every row the delete cascades to (the organization delete preview keys). */
    affected_resources: Record<string, number>;
    external_usages: PluginExternalUsage[];
    /** Delete permissions the caller lacks on what the plugin installed; delete answers 403 while non-empty. */
    missing_permissions: PluginMissingPermission[];
}

// ---------------------------------------------------------------------------
// GET /api/plugins/nav/
// ---------------------------------------------------------------------------

/** One navigation button: a ready, unsuspended plugin with a page. Needs `plugins:use`, not `read`. */
export interface PluginNavItem {
    id: number;
    name: string;
    /** PNG / SVG data URL, or `null`. Render only with `<img [src]>` after `isPluginIconUrl`. */
    icon_data_url: string | null;
}

// ---------------------------------------------------------------------------
// POST /api/plugins/{id}/ui-session/
// ---------------------------------------------------------------------------

export interface PluginUiSessionAccessEntry {
    alias: string;
    type: PluginAccessTargetType;
    actions: PluginAccessAction[];
    /** `null` when the flow or table was deleted; treat as forbidden. */
    resource_id: number | null;
}

export interface PluginUiSession {
    /**
     * Production: relative, always starts with `/api/plugin-ui/`. Dev mode: the author's
     * `http://localhost` / `http://127.0.0.1` dev server. The host must refuse anything else.
     */
    url: string;
    /** `""` in dev mode. */
    token: string;
    /** Seconds the page link stays valid; `null` in dev mode. */
    expires_in: number | null;
    /** True only for the user who set the plugin's dev URL, while the instance runs in dev mode. */
    dev_mode: boolean;
    bridge_version: number;
    plugin: PluginReference;
    access: PluginUiSessionAccessEntry[];
}

// ---------------------------------------------------------------------------
// POST /api/plugins/{id}/dev-ui/
// ---------------------------------------------------------------------------

export interface PluginDevUiRequest {
    /** `http://localhost[:port][/path]` or `http://127.0.0.1[:port][/path]`. */
    url: string;
}

// ---------------------------------------------------------------------------
// Error envelope
// ---------------------------------------------------------------------------

export type PluginErrorCode =
    | 'invalid_plugin'
    | 'invalid_plugin_secrets'
    | 'invalid'
    | 'permission_denied'
    | 'plugin_install_forbidden'
    | 'plugin_delete_forbidden'
    | 'org_membership_required'
    | 'org_context_required'
    | 'not_found'
    | 'plugin_already_installed'
    | 'plugin_resource_conflict'
    | 'plugin_suspended'
    | 'plugin_not_ready'
    | 'plugin_has_no_ui'
    | 'plugin_not_retryable'
    | 'plugin_dev_mode_disabled';

export interface PluginApiErrorBody {
    status_code: number;
    code: PluginErrorCode | string;
    /** Always human-readable and safe to show as-is. */
    message: string;
    /** Item shape depends on `code`; see the API contract. */
    errors?: unknown[];
}
