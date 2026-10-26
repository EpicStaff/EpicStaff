/// <reference types="node" />
// tsconfig.spec.json loads only the Vitest globals' types; this spec alone needs Node's (`@types/node`).
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
    PLUGIN_AUTHORIZE_PARAMETERS,
    PLUGIN_LOGIN_CONTINUE_PATTERN,
    PLUGIN_LOGIN_PATHS,
} from './constants/plugin-login-protocol.constants';

/**
 * The single source of login protocol 1, shared with the JS SDK and Django; found from this file, not the working
 * directory. Not `new URL(path, import.meta.url)`: the test bundler rewrites that pattern into a dev-server address.
 */
const CONTRACT_PATH = resolve(
    dirname(fileURLToPath(import.meta.url)),
    '../../../../../plugin-sdk/contracts/login-protocol.json'
);

interface LoginProtocolContract {
    paths: { authorize: string; login_continue: string; choose_org: string };
    authorize_params: string[];
    patterns: { continue: string };
}

describe('login protocol constants equal plugin-sdk/contracts/login-protocol.json', () => {
    const contract = JSON.parse(readFileSync(CONTRACT_PATH, 'utf8')) as LoginProtocolContract;

    it('the pages and the authorize path', () => {
        expect(PLUGIN_LOGIN_PATHS).toEqual({
            authorize: contract.paths.authorize,
            loginContinue: contract.paths.login_continue,
            chooseOrg: contract.paths.choose_org,
        });
    });

    it('the authorize parameters the pages use', () => {
        for (const parameter of Object.values(PLUGIN_AUTHORIZE_PARAMETERS)) {
            expect(contract.authorize_params).toContain(parameter);
        }
    });

    it('the continue pattern', () => {
        // Compared as compiled patterns, because `RegExp#source` escapes every "/".
        expect(PLUGIN_LOGIN_CONTINUE_PATTERN.source).toBe(new RegExp(contract.patterns.continue).source);
    });
});
