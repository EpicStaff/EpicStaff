/** Every `code` the plugin endpoints answer with, and the generic ones the frontend may meet on them. */
export type PluginErrorCode =
    | 'not_authenticated'
    | 'permission_denied'
    | 'org_context_required'
    | 'org_membership_required'
    | 'organization_not_found'
    | 'organization_inactive'
    | 'invalid'
    | 'unsupported_media_type'
    | 'invalid_plugin'
    | 'invalid_signature'
    | 'package_too_large'
    | 'plugin_upgrade_unavailable'
    | 'plugin_package_not_found'
    | 'package_not_pending'
    | 'package_file_mismatch'
    | 'untrusted_not_acknowledged'
    | 'plugin_not_found'
    | 'invalid_authorize_request'
    | 'plugin_not_running'
    | 'plugin_already_granted'
    | 'plugin_has_no_backend'
    | 'invalid_plugin_settings'
    | 'invalid_plugin_limits'
    | 'no_plugin_node'
    | 'no_plugin_database_server'
    | 'grant_not_found'
    | 'hook_not_retryable'
    | 'grant_not_suspendable'
    | 'grant_not_suspended'
    | 'plugin_suspended'
    | 'invalid_purge_phrase'
    | 'grant_not_purgeable'
    | 'plugin_not_uninstallable'
    | 'plugin_not_uninstalling'
    | 'plugin_not_purgeable'
    | 'plugin_uninstalling'
    | 'removal_not_retryable'
    | 'hook_job_not_found'
    | 'org_removed_hook_not_retryable'
    | 'org_removed_hook_not_skippable'
    | 'plugin_version_not_newer'
    | 'plugin_not_upgradable'
    | 'review_outdated'
    | 'access_growth_not_acknowledged'
    | 'upgrade_not_cancellable'
    | 'upgrade_not_retryable'
    | 'plugin_upgrade_open'
    | 'backup_not_found'
    | 'restore_not_allowed'
    | 'invalid_restore_phrase'
    | 'plugin_development_mode_off'
    | 'throttled';

/** One problem in a refused package: `loc` is a dotted path such as `manifest.user_permissions[1].action`. */
export interface PluginErrorItem {
    loc: string;
    message: string;
}

/** A plugin API failure as the UI shows it. */
export interface PluginErrorView {
    /** The known `code`, or `null` for an unknown one or a failure without a JSON body. */
    code: PluginErrorCode | null;
    message: string;
    items: PluginErrorItem[];
}
