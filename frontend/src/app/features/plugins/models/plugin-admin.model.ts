import { PluginSettingScalar } from './plugin-backend.model';

/** A plugin user permission; shown as View, Create, Edit, Delete, Export, Use. */
export type PluginAction = 'read' | 'create' | 'update' | 'delete' | 'export' | 'use';

export type PluginTrust = 'trusted' | 'untrusted';

export type PluginReviewState = 'pending' | 'approved' | 'rejected';

/** `uninstalling`: uninstalled, its data kept until `purge_after`; `purging`: being deleted. A deleted plugin is gone. */
export type PluginState =
    | 'uploaded'
    | 'provisioning'
    | 'running'
    | 'failed'
    | 'maintenance'
    | 'uninstalling'
    | 'purging';

/**
 * What a SuperAdmin can do to a whole plugin. `upgrade`: approve the pending package as an upgrade; `restore_backup`:
 * restore a backup the open upgrade took.
 */
export type PluginLifecycleAction =
    | 'uninstall'
    | 'reinstall'
    | 'purge'
    | 'retry_removal'
    | 'upgrade'
    | 'cancel_upgrade'
    | 'retry_upgrade'
    | 'restore_backup';

export type PluginGrantState =
    | 'granting'
    | 'active'
    | 'install_failed'
    | 'upgrading'
    | 'upgrade_failed'
    | 'suspended'
    | 'purging';

export type PluginSignatureStatus = 'valid' | 'absent' | 'unknown_key';

/**
 * The review warnings, in the order the server sends them. `runs_code_in_sandbox`: through flows or tools, the plugin can
 * have code run in EpicStaff's sandbox, whose network its outbound hosts do not bound.
 */
export type PluginReviewWarningCode =
    | 'untrusted_package'
    | 'runs_code_in_sandbox'
    | 'flows_use_missing'
    | 'wildcard_outbound_host';

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

/** What a new version adds that the SuperAdmin must approve before it can be installed. */
export interface PluginAccessGrowth {
    requires_acknowledgement: boolean;
    /** Only the actions the version before does not declare. */
    access: PluginDeclaredAccess[];
    outbound_hosts: PluginOutboundHost[];
    /** `widened`: the path was declared before, with fewer methods or lower limits, or as `exact`. */
    public_paths: (PluginPublicPath & { change: 'new' | 'widened' })[];
}

/** A setting the new version cannot start without: required with no value, or a stored value it refuses. */
export interface PluginSettingNeeded {
    key: string;
    type: string;
    label: string;
    description: string;
    reason: 'required' | 'invalid';
    /** The options of an `enum`, else `null`. */
    values: string[] | null;
}

export type PluginHookKind = 'install' | 'upgrade' | 'org_removed';

/** What upgrading the installed plugin to a pending package changes, compared with the latest approved version. */
export interface PluginUpgradeReview {
    /** Send it back as `reviewed_against_package_id`: an approval is refused once it is no longer the baseline. */
    baseline_package_id: number;
    /** The version the plugin runs now. */
    from_version: string;
    /** The failed upgrade's target this package replaces; the new access is shown against it. */
    replaces_version: string | null;
    trust_change: 'none' | 'became_untrusted' | 'became_trusted' | 'signer_changed';
    /** The plugin goes offline while it is upgraded (it has a backend now). */
    maintenance: boolean;
    backend: 'unchanged' | 'added';
    database: 'unchanged' | 'added' | 'none';
    /** The migration files the database has not run yet. */
    migrations_added: string[];
    hooks_added: PluginHookKind[];
    hooks_removed: PluginHookKind[];
    has_upgrade_hook: boolean;
    user_permissions: { added: PluginAction[]; removed: PluginAction[]; defaults_changed: PluginAction[] };
    settings: { added: string[]; removed: string[]; needed: PluginSettingNeeded[] };
    limits_changed: string[];
    /** `database_size_bytes` as the node last reported it. */
    backup: { required: boolean; database_name: string | null; database_size_bytes: number | null };
    /** Organizations active now that are offline until their upgrade finishes. */
    organizations_going_offline: number;
    /** Whether the upgrade can still be cancelled once it starts (not for a version that adds a backend). */
    cancellable: boolean;
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
    /** `null` for a first install and for an approved package. */
    access_growth: PluginAccessGrowth | null;
    /** `null` for a first install and for an approved package. */
    upgrade: PluginUpgradeReview | null;
}

/** What the approval sends. An upgrade must name the package its review was computed against. */
export interface PluginApproveRequest {
    untrusted_acknowledged?: boolean;
    access_growth_acknowledged?: boolean;
    reviewed_against_package_id?: number;
    /** Values for the settings the new version needs; only the target version's keys. */
    settings?: Record<string, PluginSettingScalar | null>;
}

export type PluginUpgradeStage = 'preparing' | 'maintenance' | 'migrating' | 'done' | 'cancelled' | 'abandoned';

/** The plugin node's last step of an upgrade. */
export type PluginUpgradeStep = 'download' | 'verify' | 'build' | 'drain' | 'stop' | 'backup' | 'migrate' | 'start';

export type PluginBackupReason = 'pre_upgrade' | 'pre_restore';

export type PluginRestoreState = 'pending' | 'running' | 'succeeded' | 'failed';

export type PluginRestoreStep = 'verify' | 'backup' | 'close' | 'recreate' | 'restore' | 'settings' | 'assert';

/** A restore of a backup of the plugin's database, during an upgrade that failed. */
export interface PluginRestore {
    id: number;
    /** The backup restored; `id` is `null` once the backup is deleted, `reason` when the server no longer knows it. */
    backup: { id: number | null; file_name: string; reason: PluginBackupReason | null };
    state: PluginRestoreState;
    step: PluginRestoreStep | null;
    /** The backup of the database taken just before the restore, to undo it. */
    pre_restore_backup_id: number | null;
    last_error: string | null;
    requested_by: PluginUserRef | null;
    requested_at: string;
    finished_at: string | null;
}

/** An upgrade of the plugin from one version to another. */
export interface PluginUpgrade {
    id: number;
    from_version: string;
    to_version: string;
    stage: PluginUpgradeStage;
    step: PluginUpgradeStep | null;
    failed: boolean;
    failed_at: string | null;
    last_error: string | null;
    adds_backend: boolean;
    /** The database already holds changes of `to_version`, so Cancel is no longer possible without a restore. */
    database_changed: boolean;
    backup_id: number | null;
    /** The latest restore of this upgrade. */
    restore: PluginRestore | null;
    started_by: PluginUserRef | null;
    started_at: string;
    maintenance_started_at: string | null;
    migrations_started_at: string | null;
    finished_at: string | null;
}

/** A backup of the plugin's database the plugin node holds. */
export interface PluginBackup {
    id: number;
    file_name: string;
    reason: PluginBackupReason;
    /** The plugin version whose migrations the database held. */
    version: string;
    /** The upgrade it was taken for. */
    upgrade: { id: number; to_version: string } | null;
    size_bytes: number;
    created_at: string;
    restorable: boolean;
    /** `earlier_upgrade`: taken for an upgrade that is closed; `not_now`: no failed upgrade allows a restore now. */
    not_restorable_reason: 'earlier_upgrade' | 'not_now' | 'mismatch' | null;
}

/** `GET .../backups/`: the present backups, newest first, and the phrase a restore must be confirmed with. */
export interface PluginBackupList {
    verification_phrase: string;
    backups: PluginBackup[];
}

export interface PluginPendingPackage {
    id: number;
    version: string;
    trust: PluginTrust;
}

/** Where a plugin's requests go on the author's machine while it is in development. */
export interface PluginDevelopmentPorts {
    /** The author's backend, reached at `host.docker.internal:<port>`. */
    backend_port: number | null;
    /** The author's frontend development server, served on the plugin's own host. */
    spa_port: number | null;
}

export interface PluginSummary {
    identifier: string;
    name: string;
    description: string;
    state: PluginState;
    /** Of the current package, else of the pending one; `null` when the plugin has neither. */
    trust: PluginTrust | null;
    /** `null` until the first approval. */
    current_version: string | null;
    /** `null` until the first approval. */
    icon_url: string | null;
    frame_origin: string;
    /** Grants in state `active`. */
    grant_count: number;
    pending_package: PluginPendingPackage | null;
    created_at: string;
    /**
     * Set while the plugin is uninstalled: when its data is deleted unless it is reinstalled; kept once its deletion
     * has started.
     */
    purge_after: string | null;
    /**
     * A data removal failed for good, the node failed to remove the plugin, a deleting grant has an error, the open
     * upgrade or its latest restore failed, or an organization's upgrade failed.
     */
    needs_attention: boolean;
    /** The open upgrade. */
    upgrade: { to_version: string; stage: PluginUpgradeStage; failed: boolean } | null;
    /** The stored development target; `null` unless development mode is on and a target is stored. */
    development: PluginDevelopmentPorts | null;
}

/** Where the plugin node is with removing a plugin being deleted; `not_needed` for a plugin without a placement. */
export type PluginPurgeNodeState = 'waiting' | 'removing' | 'failed' | 'not_needed';

/** How far the deletion of a plugin has come. */
export interface PluginPurgeProgress {
    grants_left: number;
    /** Data removals pending or running. */
    data_removals_waiting: number;
    data_removals_failed: number;
    node: PluginPurgeNodeState;
    node_error: string | null;
}

export interface PluginDetail extends PluginSummary {
    current_package: PackageReview | null;
    /** What the plugin allows in its current state. The server decides; the buttons follow this list only. */
    allowed_actions: PluginLifecycleAction[];
    uninstall_requested_at: string | null;
    purge_started_at: string | null;
    /** Set while the plugin is being deleted. */
    purge_progress: PluginPurgeProgress | null;
    open_upgrade: PluginUpgrade | null;
    /** The latest upgrade that is closed. */
    last_upgrade: PluginUpgrade | null;
    /** Organizations whose upgrade hook has not finished, and those whose upgrade failed. */
    upgrade_hooks: { upgrading: number; upgrade_failed: number };
    /** Plugin development mode is on on this deployment: the Development tab is offered. */
    development_mode: boolean;
}

/** `skipped`: a SuperAdmin or the platform gave up on a data removal. */
export type PluginHookJobState = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped';

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

/** The latest run of the plugin's upgrade hook for one organization; it may belong to an earlier upgrade. */
export interface PluginUpgradeHook {
    state: PluginHookJobState;
    attempt: number;
    /** The version the organization was upgraded from. */
    from_version: string | null;
    /** When a failed attempt is tried again by itself. */
    next_attempt_at: string | null;
    started_at: string | null;
    finished_at: string | null;
    error: string | null;
}

/** What a SuperAdmin can do to a grant. */
export type PluginGrantAction = 'suspend' | 'resume' | 'retry_install' | 'retry_upgrade' | 'purge';

/** Why a grant is suspended: on its own, or because the whole plugin was uninstalled. */
export type PluginGrantSuspensionCause = 'grant' | 'uninstall';

/** What a SuperAdmin can do to a data removal. */
export type PluginOrgRemovedJobAction = 'retry' | 'skip';

/**
 * A run of the plugin's organization removed hook, which deletes the plugin's own data for one organization ("data
 * removal"). It outlives the grant and the organization.
 */
export interface PluginOrgRemovedJob {
    id: number;
    /** `name` as it was when the job was made; `exists` is `false` once the organization is deleted. */
    organization: { id: number; name: string; exists: boolean };
    grant_id: number | null;
    state: PluginHookJobState;
    attempt: number;
    first_attempt_at: string | null;
    next_attempt_at: string | null;
    /** Until when failed attempts are retried by themselves. */
    retry_until: string | null;
    finished_at: string | null;
    error: string | null;
    created_at: string;
    /** What the job allows now. The server decides; the buttons follow this list only. */
    allowed_actions: PluginOrgRemovedJobAction[];
}

/** `open`: pending, running or failed; `finished`: succeeded or skipped. */
export type PluginOrgRemovedJobFilter = 'open' | 'finished' | 'all';

/** The filters of a plugin's data removal list. */
export interface PluginOrgRemovedJobQuery {
    state: PluginOrgRemovedJobFilter;
    /** Only the jobs of organizations deleted since. */
    deletedOrganizations: boolean;
    page: number;
    pageSize: number;
}

export interface PluginGrant {
    id: number;
    plugin_identifier: string;
    organization: PluginOrganizationRef;
    /**
     * `granting` while the install hook runs; `install_failed` when it failed (a SuperAdmin may retry); `upgrading` and
     * `upgrade_failed` likewise for the upgrade hook.
     */
    state: PluginGrantState;
    /** What the grant allows in its current state. The server decides; the buttons follow this list only. */
    allowed_actions: PluginGrantAction[];
    granted_by: PluginUserRef | null;
    granted_at: string;
    /** Set while the grant is suspended. */
    suspended_at: string | null;
    /** Until when a suspended grant keeps the plugin's data in the organization. */
    purge_after: string | null;
    /** The install or upgrade hook's last error. */
    last_hook_error: string | null;
    /** `null` for a plugin without a backend. */
    service_account: PluginGrantServiceAccount | null;
    /** `null` for a plugin without an install hook. */
    install_hook: PluginInstallHook | null;
    /** What the plugin's service account created in the organization and still exists. */
    owned_resource_count: number;
    /** Set while the grant is suspended, and kept while its data is deleted. */
    suspension_cause: PluginGrantSuspensionCause | null;
    /** Set while the grant's data is being deleted. */
    purge_started_at: string | null;
    /** Why something the plugin owns in the organization could not be deleted yet. */
    last_purge_error: string | null;
    /** The latest data removal for the grant's organization; `null` when there is none. */
    org_removed_hook: PluginOrgRemovedJob | null;
    /** The plugin version this organization was last brought to; `null` until its install finished. */
    installed_version: string | null;
    /** `null` until the organization's first upgrade hook. */
    upgrade_hook: PluginUpgradeHook | null;
}

/** One step of a package upload: progress while the bytes go up, then the review of the stored package. */
export type PluginUploadEvent =
    | { kind: 'progress'; loaded: number; total: number | null }
    | { kind: 'done'; review: PackageReview };
