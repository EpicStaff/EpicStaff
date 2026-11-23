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
    'plugin_version_not_newer',
    'plugin_not_upgradable',
    'review_outdated',
    'access_growth_not_acknowledged',
    'upgrade_not_cancellable',
    'upgrade_not_retryable',
    'plugin_upgrade_open',
    'backup_not_found',
    'restore_not_allowed',
    'invalid_restore_phrase',
    'plugin_development_mode_off',
    'throttled',
];

/** Codes the UI shows with the server's own message. */
const SERVER_MESSAGE_CODES: PluginErrorCode[] = ['plugin_suspended', 'plugin_version_not_newer'];

describe('toPluginErrorView', () => {
    it('has a message for every code the plugin endpoints answer with, and no other', () => {
        expect(Object.keys(PLUGIN_ERROR_MESSAGES).sort()).toEqual([...ENDPOINT_CODES].sort());
    });

    it.each(ENDPOINT_CODES.filter((code) => !SERVER_MESSAGE_CODES.includes(code)))('maps %s to its message', (code) => {
        const view = toPluginErrorView(
            failure(400, {
                type: 'client_error',
                errors: [{ code, detail: 'server text', attr: null, context: null }],
            }),
            'fallback'
        );

        expect(view.code).toBe(code);
        expect(view.message).toBe(PLUGIN_ERROR_MESSAGES[code]);
    });

    it("shows the server's message for a refused run, which names the plugin", () => {
        const message = 'This run uses resources of the plugin "Weather", which is suspended in this organization.';
        const view = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [
                    {
                        code: 'plugin_suspended',
                        detail: message,
                        attr: null,
                        context: { plugin: { identifier: 'weather', name: 'Weather' }, organization: { id: 3 } },
                    },
                ],
            }),
            'fallback'
        );

        expect(view).toEqual({ code: 'plugin_suspended', message, items: [] });
    });

    it("shows the server's sentence for a version that is not newer, which names both versions", () => {
        const view = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [
                    {
                        code: 'plugin_version_not_newer',
                        detail: '0.6.0 is not newer than the installed 0.7.0.',
                        attr: null,
                        context: { installed_version: '0.7.0', latest_version: '0.7.0' },
                    },
                ],
            }),
            'fallback'
        );

        expect(view).toEqual({
            code: 'plugin_version_not_newer',
            message: '0.6.0 is not newer than the installed 0.7.0.',
            items: [],
        });
    });

    it('says development mode is off when the deployment refuses a development change', () => {
        const view = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [
                    {
                        code: 'plugin_development_mode_off',
                        detail: 'Plugin development mode is off on this deployment.',
                        attr: null,
                        context: null,
                    },
                ],
            }),
            'fallback'
        );

        expect(view).toEqual({
            code: 'plugin_development_mode_off',
            message: 'Plugin development mode is off on this deployment.',
            items: [],
        });
    });

    it('lists why a package cannot upgrade the installed plugin', () => {
        const view = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [
                    {
                        code: 'plugin_upgrade_unavailable',
                        detail: 'a new version cannot drop the backend',
                        attr: 'manifest.backend',
                        context: null,
                    },
                    {
                        code: 'plugin_upgrade_unavailable',
                        detail: '001_weather.sql is already applied; a new version must keep it unchanged',
                        attr: 'package.database/migrations/001_weather.sql',
                        context: null,
                    },
                ],
            }),
            'fallback'
        );

        expect(view.message).toBe(PLUGIN_ERROR_MESSAGES.plugin_upgrade_unavailable);
        expect(view.items.map((item) => item.attr)).toEqual([
            'manifest.backend',
            'package.database/migrations/001_weather.sql',
        ]);
    });

    it('falls back to its own text for a refused run without a server message', () => {
        const view = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [{ code: 'plugin_suspended', detail: '', attr: null, context: null }],
            }),
            'fallback'
        );

        expect(view.message).toBe(PLUGIN_ERROR_MESSAGES.plugin_suspended);
    });

    it('tells to reload the list when a suspend or a resume no longer fits the grant', () => {
        const suspend = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [{ code: 'grant_not_suspendable', detail: 'Not suspendable.', attr: null, context: null }],
            }),
            'fallback'
        );
        const resume = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [{ code: 'grant_not_suspended', detail: 'Not suspended.', attr: null, context: null }],
            }),
            'fallback'
        );

        expect(suspend.message).toBe(
            "This organization's grant cannot be suspended in its current state. Reload the list."
        );
        expect(resume.message).toBe('This grant is not suspended. Reload the list.');
    });

    it('says a confirmation text that no longer matches may come from a renamed organization', () => {
        const view = toPluginErrorView(
            failure(400, {
                type: 'client_error',
                errors: [{ code: 'invalid_purge_phrase', detail: 'Invalid phrase.', attr: null, context: null }],
            }),
            'fallback'
        );

        expect(view.message).toBe(
            'The confirmation text does not match. The name may have changed; reload and try again.'
        );
    });

    it('tells to reject and upload again when the stored package no longer matches the review', () => {
        const view = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [
                    { code: 'package_file_mismatch', detail: 'Package file mismatch.', attr: null, context: null },
                ],
            }),
            "Couldn't approve the package."
        );

        expect(view.code).toBe('package_file_mismatch');
        expect(view.message).toContain('Reject it and upload it again.');
    });

    it('tells what to check when approving a database package finds no plugin database server', () => {
        const view = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [{ code: 'no_plugin_database_server', detail: 'No server.', attr: null, context: null }],
            }),
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
            failure(400, {
                type: 'client_error',
                errors: [{ code: 'plugin_feature_unavailable', detail: 'Server text.', attr: null, context: null }],
            }),
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

    it('reads the {loc, message} entries of a refused package as located problems', () => {
        const view = toPluginErrorView(
            failure(400, {
                type: 'client_error',
                errors: [
                    {
                        code: 'invalid_plugin',
                        detail: 'Unknown action.',
                        attr: 'manifest.user_permissions[1].action',
                        context: null,
                    },
                ],
            }),
            'x'
        );

        expect(view.items).toEqual([
            {
                code: 'invalid_plugin',
                detail: 'Unknown action.',
                attr: 'manifest.user_permissions[1].action',
                context: null,
            },
        ]);
    });

    it('lists a problem of the whole request, which the envelope sends without attr, under its own message', () => {
        const view = toPluginErrorView(
            failure(400, {
                type: 'validation_error',
                errors: [
                    {
                        code: 'invalid',
                        detail: 'needs a backend port or a frontend dev server port',
                        attr: null,
                        context: null,
                    },
                    { code: 'invalid', detail: 'is the development API port', attr: 'spa_port', context: null },
                ],
            }),
            'fallback'
        );

        expect(view).toEqual({
            code: 'invalid',
            message: 'The request was not valid.',
            items: [
                {
                    code: 'invalid',
                    detail: 'needs a backend port or a frontend dev server port',
                    attr: null,
                    context: null,
                },
                { code: 'invalid', detail: 'is the development API port', attr: 'spa_port', context: null },
            ],
        });
    });

    it.each<[string, PluginErrorCode]>([
        ['its own text', 'grant_not_suspendable'],
        ["the server's sentence", 'plugin_suspended'],
    ])('does not list the one sentence of an envelope error shown with %s', (_shownWith, code) => {
        const view = toPluginErrorView(
            failure(409, {
                type: 'client_error',
                errors: [{ code, detail: 'Server sentence.', attr: null, context: null }],
            }),
            'fallback'
        );

        expect(view.items).toEqual([]);
    });

    it("uses the server's message for an unknown code, and the fallback without a JSON body", () => {
        expect(
            toPluginErrorView(
                failure(500, { type: 'server_error', errors: [{ code: 'boom', detail: 'It broke.' }] }),
                'fallback'
            ).message
        ).toBe('It broke.');
        expect(toPluginErrorView(failure(502, 'Bad gateway'), 'fallback')).toEqual({
            code: null,
            message: 'fallback',
            items: [],
        });
        expect(toPluginErrorView(new Error('not http'), 'fallback').message).toBe('fallback');
    });
});
