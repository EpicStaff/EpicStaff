import { HttpErrorResponse } from '@angular/common/http';

import { PluginErrorCode } from '../models/plugin-error.model';
import { PLUGIN_ERROR_MESSAGES, toPluginErrorView } from './plugin-error-message.util';

function failure(status: number, body: unknown): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: body });
}

/** Every code the plugin endpoints answer with. */
const CONTRACT_CODES: PluginErrorCode[] = [
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
    'plugin_feature_unavailable',
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
    'grant_not_found',
    'hook_not_retryable',
    'throttled',
];

describe('toPluginErrorView', () => {
    it('has a message for every code of the contract, and no other', () => {
        expect(Object.keys(PLUGIN_ERROR_MESSAGES).sort()).toEqual([...CONTRACT_CODES].sort());
    });

    it.each(CONTRACT_CODES)('maps %s to its message', (code) => {
        const view = toPluginErrorView(failure(400, { status_code: 400, code, message: 'server text' }), 'fallback');

        expect(view.code).toBe(code);
        expect(view.message).toBe(PLUGIN_ERROR_MESSAGES[code]);
    });

    it('tells to reject and upload again when the stored package no longer matches the review', () => {
        const view = toPluginErrorView(
            failure(409, { status_code: 409, code: 'package_file_mismatch', message: 'Package file mismatch.' }),
            "Couldn't approve the package."
        );

        expect(view.code).toBe('package_file_mismatch');
        expect(view.message).toContain('Reject it and upload it again.');
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
