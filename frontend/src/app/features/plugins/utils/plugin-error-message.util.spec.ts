import { HttpErrorResponse } from '@angular/common/http';

import { PluginErrorCode } from '../models/plugin-error.model';
import { PLUGIN_ERROR_MESSAGES, toPluginErrorView } from './plugin-error-message.util';

function failure(status: number, body: unknown): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: body });
}

/** Every code the plugin endpoints answer with. */
const ENDPOINT_CODES: PluginErrorCode[] = [
    'not_authenticated',
    'permission_denied',
    'org_context_required',
    'org_membership_required',
    'organization_not_found',
    'organization_inactive',
    'invalid',
    'unsupported_media_type',
    'invalid_plugin',
    'invalid_signature',
    'package_too_large',
    'plugin_upgrade_unavailable',
    'plugin_package_not_found',
    'package_not_pending',
    'package_file_mismatch',
    'untrusted_not_acknowledged',
    'plugin_not_found',
    'invalid_authorize_request',
    'plugin_not_running',
    'plugin_already_granted',
    'plugin_has_no_backend',
    'invalid_plugin_settings',
    'invalid_plugin_limits',
    'no_plugin_node',
    'no_plugin_database_server',
    'grant_not_found',
    'hook_not_retryable',
    'grant_not_suspendable',
    'grant_not_suspended',
    'plugin_suspended',
    'invalid_purge_phrase',
    'grant_not_purgeable',
    'plugin_not_uninstallable',
    'plugin_not_uninstalling',
    'plugin_not_purgeable',
    'plugin_uninstalling',
    'removal_not_retryable',
    'hook_job_not_found',
    'org_removed_hook_not_retryable',
    'org_removed_hook_not_skippable',
    'throttled',
];

/** Codes the UI shows with the server's own message. */
const SERVER_MESSAGE_CODES: PluginErrorCode[] = ['plugin_suspended'];

describe('toPluginErrorView', () => {
    it('has a message for every code the plugin endpoints answer with, and no other', () => {
        expect(Object.keys(PLUGIN_ERROR_MESSAGES).sort()).toEqual([...ENDPOINT_CODES].sort());
    });

    it.each(ENDPOINT_CODES.filter((code) => !SERVER_MESSAGE_CODES.includes(code)))('maps %s to its message', (code) => {
        const view = toPluginErrorView(failure(400, { status_code: 400, code, message: 'server text' }), 'fallback');

        expect(view.code).toBe(code);
        expect(view.message).toBe(PLUGIN_ERROR_MESSAGES[code]);
    });

    it("shows the server's message for a refused run, which names the plugin", () => {
        const message = 'This run uses resources of the plugin "Weather", which is suspended in this organization.';
        const view = toPluginErrorView(
            failure(409, {
                status_code: 409,
                code: 'plugin_suspended',
                message,
                plugin: { identifier: 'weather', name: 'Weather' },
                organization: { id: 3 },
            }),
            'fallback'
        );

        expect(view).toEqual({ code: 'plugin_suspended', message, items: [] });
    });

    it('falls back to its own text for a refused run without a server message', () => {
        const view = toPluginErrorView(failure(409, { status_code: 409, code: 'plugin_suspended' }), 'fallback');

        expect(view.message).toBe(PLUGIN_ERROR_MESSAGES.plugin_suspended);
    });

    it('tells to reload the list when a suspend or a resume no longer fits the grant', () => {
        const suspend = toPluginErrorView(
            failure(409, { status_code: 409, code: 'grant_not_suspendable', message: 'Not suspendable.' }),
            'fallback'
        );
        const resume = toPluginErrorView(
            failure(409, { status_code: 409, code: 'grant_not_suspended', message: 'Not suspended.' }),
            'fallback'
        );

        expect(suspend.message).toBe(
            "This organization's grant cannot be suspended in its current state. Reload the list."
        );
        expect(resume.message).toBe('This grant is not suspended. Reload the list.');
    });

    it('says a confirmation text that no longer matches may come from a renamed organization', () => {
        const view = toPluginErrorView(
            failure(400, { status_code: 400, code: 'invalid_purge_phrase', message: 'Invalid phrase.' }),
            'fallback'
        );

        expect(view.message).toBe(
            'The confirmation text does not match. The name may have changed; reload and try again.'
        );
    });

    it('tells to reject and upload again when the stored package no longer matches the review', () => {
        const view = toPluginErrorView(
            failure(409, { status_code: 409, code: 'package_file_mismatch', message: 'Package file mismatch.' }),
            "Couldn't approve the package."
        );

        expect(view.code).toBe('package_file_mismatch');
        expect(view.message).toContain('Reject it and upload it again.');
    });

    it('tells what to check when approving a database package finds no plugin database server', () => {
        const view = toPluginErrorView(
            failure(409, { status_code: 409, code: 'no_plugin_database_server', message: 'No server.' }),
            "Couldn't approve the package."
        );

        expect(view.code).toBe('no_plugin_database_server');
        expect(view.message).toBe(
            'EpicStaff has no plugin database server registered. Check that plugins are enabled, then restart ' +
                'django_app.'
        );
    });

    it('no longer knows the code for a package needing a feature this version lacks', () => {
        const view = toPluginErrorView(
            failure(400, { status_code: 400, code: 'plugin_feature_unavailable', message: 'Server text.' }),
            'fallback'
        );

        expect(view.code).toBeNull();
        expect(view.message).toBe('Server text.');
    });

    it('treats any 413 as package_too_large, also the HTML page nginx answers with', () => {
        const view = toPluginErrorView(failure(413, '<html><body>413 Request Entity Too Large</body></html>'), 'x');

        expect(view).toEqual({
            code: 'package_too_large',
            message: PLUGIN_ERROR_MESSAGES.package_too_large,
            items: [],
        });
    });

    it('keeps the well-formed errors[] items of a refused package', () => {
        const view = toPluginErrorView(
            failure(400, {
                status_code: 400,
                code: 'invalid_plugin',
                message: 'Invalid plugin.',
                errors: [
                    { loc: 'manifest.user_permissions[1].action', message: 'Unknown action.' },
                    { loc: 7, message: 'dropped' },
                    'dropped',
                ],
            }),
            'x'
        );

        expect(view.items).toEqual([{ loc: 'manifest.user_permissions[1].action', message: 'Unknown action.' }]);
    });

    it("uses the server's message for an unknown code, and the fallback without a JSON body", () => {
        expect(toPluginErrorView(failure(500, { code: 'boom', message: 'It broke.' }), 'fallback').message).toBe(
            'It broke.'
        );
        expect(toPluginErrorView(failure(502, 'Bad gateway'), 'fallback')).toEqual({
            code: null,
            message: 'fallback',
            items: [],
        });
        expect(toPluginErrorView(new Error('not http'), 'fallback').message).toBe('fallback');
    });
});
