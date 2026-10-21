/** A plugin user permission; shown as View, Create, Edit, Delete, Export, Use. */
export type PluginAction = 'read' | 'create' | 'update' | 'delete' | 'export' | 'use';

export type PluginTrust = 'trusted' | 'untrusted';

export type PluginReviewState = 'pending' | 'approved' | 'rejected';

export type PluginState =
    | 'uploaded'
    | 'provisioning'
    | 'running'
    | 'failed'
    | 'maintenance'
    | 'uninstalling'
    | 'purging'
    | 'removed';

export type PluginGrantState =
    | 'granting'
    | 'active'
    | 'install_failed'
    | 'upgrading'
    | 'upgrade_failed'
    | 'suspended'
    | 'purging';

export type PluginSignatureStatus = 'valid' | 'absent' | 'unknown_key';

export type PluginReviewWarningCode = 'untrusted_package' | 'flows_use_missing' | 'wildcard_outbound_host';

export interface PluginUserRef {
    id: number;
    email: string;
}

export interface PluginOrganizationRef {
    id: number;
    name: string;
}

export interface PluginPackageContents {
    has_spa: boolean;
    has_backend: boolean;
    has_database: boolean;
    spa_file_count: number;
    spa_bytes: number;
    wheel_count: number;
    migration_count: number;
}

export interface PluginDeclaredAccess {
    resource_type: string;
    resource_label: string;
    actions: PluginAction[];
    reason: string;
}

export interface PluginBuiltInRoleDefaults {
    org_admin: boolean;
    member: boolean;
    viewer: boolean;
}

export interface PluginUserPermission {
    action: PluginAction;
    label: string;
    description: string;
    defaults: PluginBuiltInRoleDefaults;
}

export interface PluginPublicPath {
    path: string;
    match: 'exact' | 'prefix';
    methods: string[];
    rate_limit_per_minute: number;
    max_body_kb: number;
}

export interface PluginOutboundHost {
    host: string;
    reason: string;
}

export interface PluginSettingDeclaration {
    key: string;
    type: string;
    label: string;
    description: string;
    required: boolean;
    has_default: boolean;
}

export interface PluginLimits {
    memory_mb: number;
    db_connections: number;
    statement_timeout_seconds: number;
    requests_per_minute: number;
    cpu_priority: 'normal' | 'low';
}

export interface PluginHooks {
    install: boolean;
    upgrade: boolean;
    org_removed: boolean;
}

export interface PluginReviewWarning {
    code: PluginReviewWarningCode;
    message: string;
}

/** Everything a SuperAdmin reviews before approving a package (`GET .../packages/{id}/review/`). */
export interface PackageReview {
    id: number;
    plugin_identifier: string;
    version: string;
    name: string;
    description: string;
    publisher: { name: string; url: string | null };
    /** `data:image/svg+xml;base64,…` or `data:image/png;base64,…`; rendered only as an `<img>`. */
    icon_data_url: string;
    trust: PluginTrust;
    signature: PluginSignatureStatus;
    /** `key_id` is 16 hex characters; `key_name` only when the key is trusted. */
    signer: { key_name: string | null; key_id: string } | null;
    review_state: PluginReviewState;
    sha256: string;
    size: number;
    uploaded_at: string;
    uploaded_by: PluginUserRef | null;
    approved_at: string | null;
    approved_by: PluginUserRef | null;
    is_upgrade: boolean;
    current_version: string | null;
    contents: PluginPackageContents;
    access: PluginDeclaredAccess[];
    user_permissions: PluginUserPermission[];
    public_paths: PluginPublicPath[];
    outbound_hosts: PluginOutboundHost[];
    settings: PluginSettingDeclaration[];
    limits: PluginLimits | null;
    hooks: PluginHooks;
    warnings: PluginReviewWarning[];
    access_growth: null;
}

export interface PluginPendingPackage {
    id: number;
    version: string;
    trust: PluginTrust;
}

export interface PluginSummary {
    identifier: string;
    name: string;
    description: string;
    state: PluginState;
    /** Of the current package, else of the pending one. */
    trust: PluginTrust;
    /** `null` until the first approval. */
    current_version: string | null;
    /** `null` until the first approval. */
    icon_url: string | null;
    frame_origin: string;
    /** Grants in state `active`. */
    grant_count: number;
    pending_package: PluginPendingPackage | null;
    created_at: string;
}

export interface PluginDetail extends PluginSummary {
    current_package: PackageReview | null;
}

export type PluginHookJobState = 'pending' | 'running' | 'succeeded' | 'failed';

/** The account a plugin's backend acts with in one organization. */
export interface PluginGrantServiceAccount {
    created_at: string;
    /** `null` until the backend first calls EpicStaff with its key. */
    key_last_used_at: string | null;
}

/** The latest run of the plugin's install hook for one organization. */
export interface PluginInstallHook {
    state: PluginHookJobState;
    attempt: number;
    started_at: string | null;
    finished_at: string | null;
    error: string | null;
}

export interface PluginGrant {
    id: number;
    plugin_identifier: string;
    organization: PluginOrganizationRef;
    /** `granting` while the install hook runs; `install_failed` when it failed (a SuperAdmin may retry). */
    state: PluginGrantState;
    granted_by: PluginUserRef | null;
    granted_at: string;
    suspended_at: string | null;
    purge_after: string | null;
    /** The install hook's last error. */
    last_hook_error: string | null;
    /** `null` for a plugin without a backend. */
    service_account: PluginGrantServiceAccount | null;
    /** `null` for a plugin without an install hook. */
    install_hook: PluginInstallHook | null;
    /** What the plugin's service account created in the organization and still exists. */
    owned_resource_count: number;
}

/** One step of a package upload: progress while the bytes go up, then the review of the stored package. */
export type PluginUploadEvent =
    | { kind: 'progress'; loaded: number; total: number | null }
    | { kind: 'done'; review: PackageReview };
