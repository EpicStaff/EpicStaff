import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import {
    canonicalNavPath,
    FRAME_ERROR_CODES,
    FRAME_LIMITS,
    FRAME_MESSAGE_TYPES,
    FRAME_PROTOCOL_VERSION,
    NAV_PATH_PATTERN,
    THEME_MODES,
    THEME_TOKENS,
} from '../dist/index.js';

interface FrameProtocolContract {
    protocol: number;
    message_types: string[];
    error_codes: string[];
    limits: { max_nav_path_length: number; max_nav_changes_per_minute: number; init_timeout_ms: number };
    nav_path_pattern: string;
    theme_modes: string[];
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
});
