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
    plugin_feature_unavailable:
        'This package needs a plugin backend or database, which this version of EpicStaff cannot run yet.',
    package_too_large: 'The package is larger than this deployment accepts.',
    plugin_upgrade_unavailable: 'This plugin is already installed. Installing a new version is not available yet.',
    plugin_package_not_found: 'This package no longer exists. It may have been rejected or replaced.',
    package_not_pending: 'This package was already approved or rejected.',
    package_file_mismatch:
        'The stored package is missing or no longer matches the version you reviewed, so it may have been changed or ' +
        'damaged. Reject it and upload it again.',
    untrusted_not_acknowledged: 'Confirm that you accept the risk of installing an untrusted package.',
    plugin_not_found: 'This plugin no longer exists.',
    plugin_not_running: 'The plugin is not running yet, so it cannot be granted.',
    plugin_already_granted: 'This organization already has the plugin.',
};

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
 * Turns a failed plugin request into what the UI shows: the message for a known `code`, the server's own message for
 * an unknown one, else `fallback`; and the `errors[]` items of a refused package. Any 413 is `package_too_large`,
 * because nginx may refuse an oversized upload before Django, with an HTML body.
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
    if (isPluginErrorCode(code)) return { code, message: PLUGIN_ERROR_MESSAGES[code], items };
    const serverMessage = body['message'];
    return {
        code: null,
        message: typeof serverMessage === 'string' && serverMessage ? serverMessage : fallback,
        items,
    };
}
