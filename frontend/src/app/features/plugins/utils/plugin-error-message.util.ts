import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';

import { PluginErrorCode, PluginErrorItem, PluginErrorView } from '../models/plugin-error.model';

/** What the UI says for each error code of the plugin endpoints. */
export const PLUGIN_ERROR_MESSAGES: Readonly<Record<PluginErrorCode, string>> = {
    not_authenticated: 'Your session has ended. Sign in again.',
    permission_denied: 'You do not have permission to manage plugins.',
    org_context_required: 'Choose an organization first.',
    org_membership_required: 'You are not a member of this organization.',
    organization_not_found: 'That organization no longer exists.',
    organization_inactive: 'That organization is deactivated. Reactivate it before granting plugins to it.',
    invalid: 'The request was not valid.',
    unsupported_media_type: 'Upload the package as a file.',
    invalid_plugin: 'This is not a valid plugin package. Fix the problems listed and upload it again.',
    invalid_signature:
        'The package signature does not match its contents. The package may have been changed after it was signed.',
    package_too_large: 'The package is larger than this deployment accepts.',
    plugin_upgrade_unavailable:
        'This package cannot upgrade the installed plugin. Fix the problems listed and upload a newer version.',
    plugin_package_not_found: 'This package no longer exists. It may have been rejected or replaced.',
    package_not_pending: 'This package was already approved or rejected.',
    package_file_mismatch:
        'The stored package is missing or no longer matches the version you reviewed, so it may have been changed or ' +
        'damaged. Reject it and upload it again.',
    untrusted_not_acknowledged: 'Confirm that you accept the risk of installing an untrusted package.',
    plugin_not_found: 'This plugin no longer exists.',
    invalid_authorize_request: 'This sign-in link is not valid. Open the plugin again from EpicStaff.',
    // Granting and development both answer it.
    plugin_not_running: 'The plugin is not running yet. Try again once it runs.',
    plugin_already_granted: 'This organization already has the plugin.',
    plugin_has_no_backend:
        'This plugin has no backend, so it has no settings, limits, runtime or development runtime file.',
    invalid_plugin_settings: 'Some settings are not valid. Fix the fields marked below and save again.',
    invalid_plugin_limits: 'Some limits are not valid. Fix the fields marked below and save again.',
    no_plugin_node:
        'No plugin node is registered, so a plugin with a backend cannot run. Set PLUGINS_NODE_KEY, restart ' +
        'EpicStaff and approve the package again.',
    no_plugin_database_server:
        'EpicStaff has no plugin database server registered. Check that plugins are enabled, then restart django_app.',
    grant_not_found: 'This grant no longer exists.',
    hook_not_retryable: 'The install or upgrade has not failed, so there is nothing to retry.',
    grant_not_suspendable: "This organization's grant cannot be suspended in its current state. Reload the list.",
    grant_not_suspended: 'This grant is not suspended. Reload the list.',
    // Shown only when the server sends no message of its own (see SERVER_MESSAGE_CODES).
    plugin_suspended: 'This run uses resources of a plugin that is not active in this organization.',
    invalid_purge_phrase: 'The confirmation text does not match. The name may have changed; reload and try again.',
    grant_not_purgeable:
        "This organization's data is already being deleted, or the whole plugin is being deleted. Reload the list.",
    plugin_not_uninstallable: 'This plugin cannot be uninstalled in its current state. Reload the page.',
    plugin_not_uninstalling: 'This plugin is not uninstalled, so there is nothing to reinstall. Reload the page.',
    plugin_not_purgeable: 'This plugin cannot be deleted in its current state. Reload the page.',
    plugin_uninstalling: 'This plugin is uninstalled or being deleted, so this cannot be done now.',
    removal_not_retryable: 'The plugin node has not reported a failed removal, so there is nothing to retry.',
    hook_job_not_found: 'This data removal no longer exists. Reload the list.',
    org_removed_hook_not_retryable: 'This data removal cannot be retried now. Reload the list.',
    org_removed_hook_not_skippable:
        'This data removal is running or has finished, so it cannot be skipped. Reload the list.',
    // Shown only when the server sends no message of its own (see SERVER_MESSAGE_CODES).
    plugin_version_not_newer:
        'This version is not newer than the one installed or being upgraded to. Upload a newer one.',
    plugin_not_upgradable:
        'The plugin cannot be upgraded right now. Wait until its open upgrade finishes or fails, then try again.',
    review_outdated:
        'The installed version or the upgrade under way changed since this review was loaded. Check the review again.',
    access_growth_not_acknowledged: 'Approve the new access this version asks for before you upgrade.',
    upgrade_not_cancellable: 'This upgrade cannot be cancelled in its current state. Reload the page.',
    upgrade_not_retryable: 'The upgrade has not failed, so there is nothing to retry. Reload the page.',
    plugin_upgrade_open: 'An upgrade of this plugin is under way. Cancel it or let it finish first.',
    backup_not_found: 'This backup no longer exists. Reload the list.',
    restore_not_allowed:
        'This backup cannot be restored now: only a backup of the failed upgrade under way can. Reload the list.',
    invalid_restore_phrase: 'The confirmation text does not match. Type it exactly as shown.',
    plugin_development_mode_off: 'Plugin development mode is off on this deployment.',
    throttled: 'Too many requests. Wait a moment and try again.',
};

/**
 * Codes whose server message is what the UI shows, because it names what only the server knows: the plugin, or the
 * versions it compared.
 */
const SERVER_MESSAGE_CODES: ReadonlySet<PluginErrorCode> = new Set<PluginErrorCode>([
    'plugin_suspended',
    'plugin_version_not_newer',
]);

function isPluginErrorCode(code: unknown): code is PluginErrorCode {
    return typeof code === 'string' && Object.hasOwn(PLUGIN_ERROR_MESSAGES, code);
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toErrorItems(errors: unknown): PluginErrorItem[] {
    if (!Array.isArray(errors)) return [];
    return errors.flatMap((item: unknown) =>
        isRecord(item) && typeof item['loc'] === 'string' && typeof item['message'] === 'string'
            ? [{ loc: item['loc'], message: item['message'] }]
            : []
    );
}

/**
 * Turns a failed plugin request into what the UI shows: the message for a known `code` (the server's own for a code
 * whose message names the plugin), the server's own message for an unknown code, else `fallback`; and the `errors[]`
 * items of a refused package. Any 413 is `package_too_large`, because nginx may refuse an oversized upload before
 * Django, with an HTML body.
 */
export function toPluginErrorView(error: unknown, fallback: string): PluginErrorView {
    if (!(error instanceof HttpErrorResponse)) return { code: null, message: fallback, items: [] };
    if (error.status === HttpStatusCode.PayloadTooLarge) {
        return { code: 'package_too_large', message: PLUGIN_ERROR_MESSAGES.package_too_large, items: [] };
    }
    const body: unknown = error.error;
    if (!isRecord(body)) return { code: null, message: fallback, items: [] };
    const items = toErrorItems(body['errors']);
    const code = body['code'];
    const rawMessage = body['message'];
    const serverMessage = typeof rawMessage === 'string' && rawMessage ? rawMessage : null;
    if (isPluginErrorCode(code)) {
        const message = SERVER_MESSAGE_CODES.has(code) && serverMessage ? serverMessage : PLUGIN_ERROR_MESSAGES[code];
        return { code, message, items };
    }
    return { code: null, message: serverMessage ?? fallback, items };
}
