import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';
import { runInNewContext } from 'node:vm';

import { FakeWindow, PLUGIN_ORIGIN } from './helpers/fake-window.ts';

/** The platform's callback script, as nginx serves it on every plugin host (no build step). */
const CALLBACK_SCRIPT = readFileSync(new URL('../../src/nginx/plugin-platform/callback.js', import.meta.url), 'utf8');
const CALLBACK_PATH = '/.well-known/epicstaff/callback.html';
const SILENT_PATH = '/.well-known/epicstaff/silent-callback.html';
const PENDING = 'epicstaff.login.pending';
const RESULT = 'epicstaff.login.result';
const STATE = 'S'.repeat(43);
const CODE = 'C'.repeat(43);

interface LoginProtocolContract {
    protocol: number;
    message_types: string[];
    storage_keys: Record<string, string>;
    callback_errors: string[];
    patterns: Record<string, string>;
    limits: Record<string, number>;
}

const contract = JSON.parse(
    readFileSync(new URL('../contracts/login-protocol.json', import.meta.url), 'utf8')
) as LoginProtocolContract;

/** Runs callback.js in its own realm, as the page `mode` would load it, at `path#fragment`. */
function runCallback(mode: 'interactive' | 'silent', fragment: string, framed = mode === 'silent'): FakeWindow {
    const path = mode === 'silent' ? SILENT_PATH : CALLBACK_PATH;
    const win = new FakeWindow({ framed, url: `${PLUGIN_ORIGIN}${path}#${fragment}` });
    win.document.documentElement.setAttribute('data-callback', mode);
    runInNewContext(CALLBACK_SCRIPT, { window: win, URL, URLSearchParams });
    return win;
}

function pending(overrides: Record<string, unknown> = {}): string {
    return JSON.stringify({
        state: STATE,
        code_verifier: 'v'.repeat(43),
        return_path: '/me?city=Paris#top',
        org: 3,
        created_at: Date.now(),
        ...overrides,
    });
}

/** Runs the interactive page with a pending sign-in already in the tab's storage. */
function runInteractive(fragment: string, pendingEntry: string | null = pending()): FakeWindow {
    const path = `${PLUGIN_ORIGIN}${CALLBACK_PATH}#${fragment}`;
    const win = new FakeWindow({ framed: false, url: path });
    win.document.documentElement.setAttribute('data-callback', 'interactive');
    if (pendingEntry !== null) win.sessionStorage.setItem(PENDING, pendingEntry);
    runInNewContext(CALLBACK_SCRIPT, { window: win, URL, URLSearchParams });
    return win;
}

/** The value as plain JSON: what the script made lives in another realm. */
function plain(value: unknown): unknown {
    return JSON.parse(JSON.stringify(value)) as unknown;
}

function storedResult(win: FakeWindow): unknown {
    return JSON.parse(win.sessionStorage.getItem(RESULT) ?? 'null') as unknown;
}

describe('callback.js', () => {
    test('its constants equal contracts/login-protocol.json', () => {
        const declarations = CALLBACK_SCRIPT.split('\n').filter((line) => /^ {4}const [A-Z_]+ = .+;$/.test(line));
        const constants = plain(
            runInNewContext(`(() => {
${declarations.join('\n')}
return {
    PROTOCOL, LOGIN_RESULT_MESSAGE, PENDING_KEY, RESULT_KEY, PENDING_MAX_AGE_MS, CALLBACK_ERRORS,
    STATE_PATTERN: STATE_PATTERN.source, CODE_PATTERN: CODE_PATTERN.source, RETURN_PATH_PATTERN: RETURN_PATH_PATTERN.source,
};
})()`)
        );

        assert.deepEqual(constants, {
            PROTOCOL: contract.protocol,
            LOGIN_RESULT_MESSAGE: contract.message_types[0],
            PENDING_KEY: contract.storage_keys['pending'],
            RESULT_KEY: contract.storage_keys['result'],
            PENDING_MAX_AGE_MS: (contract.limits['pending_max_age_seconds'] ?? 0) * 1000,
            CALLBACK_ERRORS: contract.callback_errors,
            STATE_PATTERN: new RegExp(contract.patterns['state'] ?? '').source,
            CODE_PATTERN: new RegExp(contract.patterns['code'] ?? '').source,
            RETURN_PATH_PATTERN: new RegExp(contract.patterns['return_path'] ?? '').source,
        });
    });
});

describe('callback.html', () => {
    test('strips the fragment, stores the code for the matching pending sign-in and returns with replace', () => {
        const win = runInteractive(`code=${CODE}&state=${STATE}`);

        assert.deepEqual(win.history.calls, [{ method: 'replaceState', url: `${PLUGIN_ORIGIN}${CALLBACK_PATH}` }]);
        assert.deepEqual(storedResult(win), { state: STATE, code: CODE });
        assert.deepEqual(win.location.replacements, [`${PLUGIN_ORIGIN}/me?city=Paris#top`]);
        assert.deepEqual(win.location.assignments, []);
        assert.notEqual(win.sessionStorage.getItem(PENDING), null, 'the SDK takes the pending entry');
    });

    test('stores an error EpicStaff uses, and drops a code of the wrong shape or an unknown error', () => {
        assert.deepEqual(storedResult(runInteractive(`error=access_denied&state=${STATE}`)), {
            state: STATE,
            error: 'access_denied',
        });
        assert.deepEqual(storedResult(runInteractive(`code=short&state=${STATE}`)), { state: STATE });
        assert.deepEqual(storedResult(runInteractive(`error=server_error&state=${STATE}`)), { state: STATE });
    });

    test('writes nothing and goes to / when the state does not match, the entry is old, or there is none', () => {
        for (const win of [
            runInteractive(`code=${CODE}&state=${'T'.repeat(43)}`),
            runInteractive(`code=${CODE}`),
            runInteractive(`code=${CODE}&state=${STATE}`, pending({ created_at: Date.now() - 600_001 })),
            runInteractive(`code=${CODE}&state=${STATE}`, '{not json'),
            runInteractive(`code=${CODE}&state=${STATE}`, null),
        ]) {
            assert.equal(win.sessionStorage.getItem(RESULT), null);
            assert.deepEqual(win.location.replacements, [`${PLUGIN_ORIGIN}/`]);
            assert.equal(win.location.href, `${PLUGIN_ORIGIN}${CALLBACK_PATH}`, 'the fragment is stripped anyway');
        }
    });

    test('returns only to a path on its own origin', () => {
        for (const returnPath of [
            '//evil.example/x',
            '/\\evil.example/x',
            'https://evil.example/',
            'javascript:alert(1)',
            '/café',
            '/a\tb',
            'me',
            '',
            42,
            `/${'x'.repeat(2048)}`,
        ]) {
            const win = runInteractive(`code=${CODE}&state=${STATE}`, pending({ return_path: returnPath }));
            assert.deepEqual(win.location.replacements, [`${PLUGIN_ORIGIN}/`], JSON.stringify(returnPath));
            assert.deepEqual(storedResult(win), { state: STATE, code: CODE }, 'the answer is still kept');
        }
    });
});

describe('silent-callback.html', () => {
    test('posts the answer to the framing page with its own origin as the target, never "*"', () => {
        const win = runCallback('silent', `code=${CODE}&state=${STATE}`);

        assert.deepEqual(plain(win.parentFrame.posted), [
            { data: { type: 'es:login-result', protocol: 1, state: STATE, code: CODE }, targetOrigin: PLUGIN_ORIGIN },
        ]);
        assert.deepEqual(win.history.calls, [{ method: 'replaceState', url: `${PLUGIN_ORIGIN}${SILENT_PATH}` }]);
        assert.deepEqual(win.location.replacements, []);
        assert.equal(win.sessionStorage.length, 0);
    });

    test('posts errors, and nothing usable for an unknown one', () => {
        const required = runCallback('silent', `error=login_required&state=${STATE}`);
        assert.deepEqual(plain(required.parentFrame.posted[0]?.data), {
            type: 'es:login-result',
            protocol: 1,
            state: STATE,
            error: 'login_required',
        });

        const unknown = runCallback('silent', `error=server_error&code=bad&state=${STATE}`);
        assert.deepEqual(plain(unknown.parentFrame.posted[0]?.data), {
            type: 'es:login-result',
            protocol: 1,
            state: STATE,
        });
    });

    test('posts nothing when top-level, or without a valid state', () => {
        const topLevel = runCallback('silent', `code=${CODE}&state=${STATE}`, false);
        assert.deepEqual(topLevel.location.replacements, []);
        assert.equal(topLevel.history.calls.length, 1, 'the fragment is still stripped');

        assert.deepEqual(runCallback('silent', `code=${CODE}`).parentFrame.posted, []);
        assert.deepEqual(runCallback('silent', `code=${CODE}&state=short`).parentFrame.posted, []);
    });
});

describe('the callback pages', () => {
    test('load only callback.js, from its platform path, and carry no inline script', () => {
        for (const [name, mode] of [
            ['callback.html', 'interactive'],
            ['silent-callback.html', 'silent'],
        ] as const) {
            const html = readFileSync(new URL(`../../src/nginx/plugin-platform/${name}`, import.meta.url), 'utf8');
            const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
            assert.equal(scripts.length, 1, name);
            assert.match(scripts[0]?.[1] ?? '', /src="\/\.well-known\/epicstaff\/callback\.js"/);
            assert.equal(scripts[0]?.[2]?.trim(), '', `${name} has no inline script`);
            assert.match(html, new RegExp(`data-callback="${mode}"`));
            assert.doesNotMatch(html, /\son[a-z]+=/i, `${name} has no inline event handler`);
        }
    });
});
