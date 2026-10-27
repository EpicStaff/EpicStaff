import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import {
    AVAILABILITY_STATES,
    canonicalNavPath,
    FRAME_ERROR_CODES,
    FRAME_LIMITS,
    FRAME_MESSAGE_TYPES,
    FRAME_PROTOCOL_VERSION,
    LOGIN_AUTHORIZE_PARAMETERS,
    LOGIN_CALLBACK_ERRORS,
    LOGIN_CODE_CHALLENGE_METHOD,
    LOGIN_LIMITS,
    LOGIN_MESSAGE_TYPES,
    LOGIN_PATHS,
    LOGIN_PATTERNS,
    LOGIN_PROMPT_VALUES,
    LOGIN_PROTOCOL_VERSION,
    LOGIN_STORAGE_KEYS,
    NAV_PATH_PATTERN,
    THEME_MODES,
    THEME_TOKENS,
} from '../dist/index.js';

interface FrameProtocolContract {
    protocol: number;
    message_types: string[];
    error_codes: string[];
    limits: {
        max_nav_path_length: number;
        max_nav_changes_per_minute: number;
        init_timeout_ms: number;
        max_availability_changes_per_minute: number;
    };
    nav_path_pattern: string;
    theme_modes: string[];
    availability_states: string[];
    theme_tokens: string[];
    canonical_vectors: { path: string; canonical: string | null }[];
}

const contract = JSON.parse(
    readFileSync(new URL('../contracts/frame-protocol.json', import.meta.url), 'utf8')
) as FrameProtocolContract;

describe('the SDK constants equal contracts/frame-protocol.json', () => {
    test('protocol version', () => {
        assert.equal(FRAME_PROTOCOL_VERSION, contract.protocol);
    });

    test('message types and error codes', () => {
        assert.deepEqual(Object.values(FRAME_MESSAGE_TYPES), contract.message_types);
        assert.deepEqual([...FRAME_ERROR_CODES], contract.error_codes);
    });

    test('limits', () => {
        assert.deepEqual(
            {
                max_nav_path_length: FRAME_LIMITS.maxNavPathLength,
                max_nav_changes_per_minute: FRAME_LIMITS.maxNavChangesPerMinute,
                init_timeout_ms: FRAME_LIMITS.initTimeoutMs,
                max_availability_changes_per_minute: FRAME_LIMITS.maxAvailabilityChangesPerMinute,
            },
            contract.limits
        );
    });

    test('navigation path grammar', () => {
        // Compared as compiled patterns, because `RegExp#source` escapes every "/".
        assert.equal(NAV_PATH_PATTERN.source, new RegExp(contract.nav_path_pattern).source);
    });

    test('canonical spelling of every vector, the same as EpicStaff computes it', () => {
        assert.ok(contract.canonical_vectors.length > 0);
        for (const vector of contract.canonical_vectors) {
            assert.equal(canonicalNavPath(vector.path), vector.canonical, JSON.stringify(vector.path));
        }
    });

    test('theme modes and tokens, in order', () => {
        assert.deepEqual([...THEME_MODES], contract.theme_modes);
        assert.deepEqual([...THEME_TOKENS], contract.theme_tokens);
    });

    test('availability states', () => {
        assert.deepEqual([...AVAILABILITY_STATES], contract.availability_states);
    });
});

interface LoginProtocolContract {
    protocol: number;
    paths: Record<string, string>;
    authorize_params: string[];
    code_challenge_method: string;
    prompt_values: string[];
    callback_errors: string[];
    message_types: string[];
    storage_keys: Record<string, string>;
    patterns: Record<string, string>;
    limits: Record<string, number>;
}

const loginContract = JSON.parse(
    readFileSync(new URL('../contracts/login-protocol.json', import.meta.url), 'utf8')
) as LoginProtocolContract;

describe('the SDK constants equal contracts/login-protocol.json', () => {
    test('protocol version, paths and authorize parameters', () => {
        assert.equal(LOGIN_PROTOCOL_VERSION, loginContract.protocol);
        assert.deepEqual(
            {
                authorize: LOGIN_PATHS.authorize,
                token: LOGIN_PATHS.token,
                callback: LOGIN_PATHS.callback,
                silent_callback: LOGIN_PATHS.silentCallback,
                callback_script: LOGIN_PATHS.callbackScript,
                login_continue: LOGIN_PATHS.loginContinue,
                choose_org: LOGIN_PATHS.chooseOrg,
            },
            loginContract.paths
        );
        assert.deepEqual([...LOGIN_AUTHORIZE_PARAMETERS], loginContract.authorize_params);
        assert.equal(LOGIN_CODE_CHALLENGE_METHOD, loginContract.code_challenge_method);
        assert.deepEqual([...LOGIN_PROMPT_VALUES], loginContract.prompt_values);
    });

    test('callback errors, message types and storage keys', () => {
        assert.deepEqual([...LOGIN_CALLBACK_ERRORS], loginContract.callback_errors);
        assert.deepEqual(Object.values(LOGIN_MESSAGE_TYPES), loginContract.message_types);
        assert.deepEqual({ ...LOGIN_STORAGE_KEYS }, loginContract.storage_keys);
    });

    test('patterns', () => {
        // Compared as compiled patterns, because `RegExp#source` escapes every "/".
        assert.deepEqual(
            {
                state: LOGIN_PATTERNS.state.source,
                code: LOGIN_PATTERNS.code.source,
                code_challenge: LOGIN_PATTERNS.codeChallenge.source,
                code_verifier: LOGIN_PATTERNS.codeVerifier.source,
                continue: LOGIN_PATTERNS.continue.source,
                return_path: LOGIN_PATTERNS.returnPath.source,
                popup_state: LOGIN_PATTERNS.popupState.source,
            },
            Object.fromEntries(
                Object.entries(loginContract.patterns).map(([name, pattern]) => [name, new RegExp(pattern).source])
            )
        );
    });

    test('limits', () => {
        assert.deepEqual(
            {
                code_ttl_seconds: LOGIN_LIMITS.codeTtlSeconds,
                token_lifetime_seconds: LOGIN_LIMITS.tokenLifetimeSeconds,
                renew_before_expiry_seconds: LOGIN_LIMITS.renewBeforeExpirySeconds,
                silent_timeout_ms: LOGIN_LIMITS.silentTimeoutMs,
                pending_max_age_seconds: LOGIN_LIMITS.pendingMaxAgeSeconds,
                popup_relay_poll_ms: LOGIN_LIMITS.popupRelayPollMs,
                popup_relay_timeout_seconds: LOGIN_LIMITS.popupRelayTimeoutSeconds,
            },
            loginContract.limits
        );
    });

    test('the package exports the contract file', () => {
        const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as {
            exports: Record<string, unknown>;
        };
        assert.equal(manifest.exports['./contracts/login-protocol.json'], './contracts/login-protocol.json');
    });
});
