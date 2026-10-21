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
    | 'plugin_feature_unavailable'
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
    | 'grant_not_found'
    | 'hook_not_retryable'
    | 'grant_not_suspendable'
    | 'grant_not_suspended'
    | 'plugin_suspended'
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
