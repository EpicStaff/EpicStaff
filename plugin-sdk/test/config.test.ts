import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { loadPlatformConfig, parsePlatformConfig, PLATFORM_CONFIG_PATH, PlatformConfigError } from '../dist/index.js';
import { configFetch, EPICSTAFF_ORIGIN } from './helpers/fake-window.ts';

const VALID = {
    plugin: { identifier: 'weather', name: 'Weather', version: '0.1.0' },
    epicstaff_origin: EPICSTAFF_ORIGIN,
    frame_protocol: 1,
    api_base: '/api/',
    login: null,
};

describe('platform config', () => {
    test('loads the well-known document from the page origin, without credentials', async () => {
        const fetchConfig = configFetch();

        const config = await loadPlatformConfig({ fetch: fetchConfig });

        assert.deepEqual(fetchConfig.urls, [PLATFORM_CONFIG_PATH]);
        assert.equal(fetchConfig.requests[0]?.credentials, 'omit');
        assert.equal(PLATFORM_CONFIG_PATH, '/.well-known/epicstaff/config.json');
        assert.deepEqual(config, VALID);
    });

    test('fails with PlatformConfigError on an HTTP error or a body that is not JSON', async () => {
        const notFound = (async () => new Response('nope', { status: 404 })) as typeof fetch;
        const notJson = (async () => new Response('<html>', { status: 200 })) as typeof fetch;

        await assert.rejects(loadPlatformConfig({ fetch: notFound }), PlatformConfigError);
        await assert.rejects(loadPlatformConfig({ fetch: notJson }), PlatformConfigError);
    });

    test('accepts http only as an exact origin', () => {
        assert.equal(
            parsePlatformConfig({ ...VALID, epicstaff_origin: 'http://epicstaff.localhost' }).epicstaff_origin,
            'http://epicstaff.localhost'
        );
        for (const origin of [
            'https://epicstaff.example.com/',
            'https://epicstaff.example.com/app',
            'https://user@epicstaff.example.com',
            'javascript:alert(1)',
            '*',
            42,
        ]) {
            assert.throws(() => parsePlatformConfig({ ...VALID, epicstaff_origin: origin }), PlatformConfigError);
        }
    });

    test('refuses another frame protocol, a missing plugin identity or a non-path api_base', () => {
        assert.throws(() => parsePlatformConfig({ ...VALID, frame_protocol: 2 }), PlatformConfigError);
        assert.throws(() => parsePlatformConfig({ ...VALID, plugin: { name: 'Weather' } }), PlatformConfigError);
        assert.throws(() => parsePlatformConfig({ ...VALID, api_base: 'https://evil.example/' }), PlatformConfigError);
        assert.throws(() => parsePlatformConfig([]), PlatformConfigError);
    });
});
