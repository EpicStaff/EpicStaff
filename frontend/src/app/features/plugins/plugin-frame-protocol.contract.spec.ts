/// <reference types="node" />
// tsconfig.spec.json loads only the Vitest globals' types; this spec alone needs Node's (`@types/node`).
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
    PLUGIN_FRAME_ERROR_CODES,
    PLUGIN_FRAME_LIMITS,
    PLUGIN_FRAME_MESSAGE_TYPES,
    PLUGIN_FRAME_PROTOCOL_VERSION,
    PLUGIN_NAV_PATH_PATTERN,
    PLUGIN_THEME_MODES,
} from './constants/plugin-frame-protocol.constants';
import { PLUGIN_THEME_TOKENS } from './services/plugin-host-theme.service';
import { canonicalNavPath } from './utils/plugin-nav-path.util';

/**
 * The single source of frame protocol 1, shared with the JS SDK; found from this file, not the working directory. Not
 * `new URL(path, import.meta.url)`: the test bundler rewrites that pattern into a dev-server address.
 */
const CONTRACT_PATH = resolve(
    dirname(fileURLToPath(import.meta.url)),
    '../../../../../plugin-sdk/contracts/frame-protocol.json'
);

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

describe('frame protocol constants equal plugin-sdk/contracts/frame-protocol.json', () => {
    const contract = JSON.parse(readFileSync(CONTRACT_PATH, 'utf8')) as FrameProtocolContract;

    it('protocol version, message types and error codes', () => {
        expect(PLUGIN_FRAME_PROTOCOL_VERSION).toBe(contract.protocol);
        expect(Object.values(PLUGIN_FRAME_MESSAGE_TYPES)).toEqual(contract.message_types);
        expect(Object.values(PLUGIN_FRAME_ERROR_CODES)).toEqual(contract.error_codes);
    });

    it('the limits EpicStaff enforces', () => {
        expect(PLUGIN_FRAME_LIMITS.maxNavPathLength).toBe(contract.limits.max_nav_path_length);
        expect(PLUGIN_FRAME_LIMITS.maxNavChangesPerMinute).toBe(contract.limits.max_nav_changes_per_minute);
    });

    it('the navigation path grammar', () => {
        // Compared as compiled patterns, because `RegExp#source` escapes every "/".
        expect(PLUGIN_NAV_PATH_PATTERN.source).toBe(new RegExp(contract.nav_path_pattern).source);
    });

    it('the canonical spelling of every vector, the same as the JS SDK computes it', () => {
        expect(contract.canonical_vectors.length).toBeGreaterThan(0);
        for (const vector of contract.canonical_vectors) {
            expect(canonicalNavPath(vector.path), JSON.stringify(vector.path)).toBe(vector.canonical);
        }
    });

    it('theme modes, and the theme tokens in order', () => {
        expect([...PLUGIN_THEME_MODES]).toEqual(contract.theme_modes);
        expect(Object.keys(PLUGIN_THEME_TOKENS)).toEqual(contract.theme_tokens);
    });
});
